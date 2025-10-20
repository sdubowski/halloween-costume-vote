import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from PIL import Image, ImageOps
import pillow_heif
import qrcode

pillow_heif.register_heif_opener()

# --------- KONFIG ŚCIEŻEK POD HOSTING ----------
# Na platformie podmontujesz dysk do /data (lub innej ścieżki) i ustawisz ENV:
# DB_PATH=/data/app.db
# UPLOAD_DIR=/data/uploads
# QR_DIR=/data/qrs
DB_PATH    = os.environ.get("DB_PATH",    os.path.join(os.getcwd(), "instance", "app.db"))
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.getcwd(), "static", "uploads"))
QR_DIR     = os.environ.get("QR_DIR",     os.path.join(os.getcwd(), "static", "qrs"))

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(QR_DIR, exist_ok=True)

# -----------------------------------------------

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)

    # Ustaw własny SECRET_KEY w panelu (ENV). Lokalnie fallback (zmień na swój!)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-me')


    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    app.config['UPLOAD_FOLDER'] = UPLOAD_DIR
    app.config['QR_FOLDER'] = QR_DIR

    db.init_app(app)
    with app.app_context():
        db.create_all()

    register_routes(app)
    return app


def _event_join_link(event_id):
    return url_for('join', event_id=event_id, _external=True)

def _qr_png(path, data):
    img = qrcode.make(data)
    img.save(path)

def _get_current_user_id_for_event(event_id: int):
    data = session.get('user_ids', {})
    return data.get(str(event_id))

def _set_current_user_id_for_event(event_id: int, user_id: int):
    data = session.get('user_ids', {})
    data[str(event_id)] = user_id
    session['user_ids'] = data



# --- MODELE ---
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    expected_players = db.Column(db.Integer, nullable=False, default=0)
    is_voting_open = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    users = db.relationship('User', backref='event', lazy=True, cascade="all, delete-orphan")
    votes = db.relationship('Vote', backref='event', lazy=True, cascade="all, delete-orphan")


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    photo_path = db.Column(db.String(255), nullable=True)


class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    voter_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    candidate_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


def register_routes(app: Flask):

    @app.get('/')
    def index():
        return render_template('admin_create.html')

    @app.post('/admin/create')
    def admin_create():
        name = request.form.get('name', '').strip()
        expected_players = request.form.get('expected_players', '').strip()
        if not name or not expected_players.isdigit():
            flash('Podaj nazwę wydarzenia i liczbę uczestników.', 'danger')
            return redirect(url_for('index'))

        ev = Event(name=name, expected_players=int(expected_players))
        db.session.add(ev)
        db.session.commit()

        join_url = _event_join_link(ev.id)
        qr_path = os.path.join(app.config['QR_FOLDER'], f'event_{ev.id}.png')
        _qr_png(qr_path, join_url)
        qr_rel = f'/static/qrs/event_{ev.id}.png'

        return render_template('admin_event.html', event=ev, join_url=join_url, qr_path=qr_rel)

    # --- dołączenie użytkownika ---
    @app.get('/e/<int:event_id>/join')
    def join(event_id):
        ev = Event.query.get_or_404(event_id)
        user_id = _get_current_user_id_for_event(ev.id)
        if user_id:
            return redirect(url_for('wait', event_id=ev.id))
        return render_template('register.html', event=ev)

    @app.post('/e/<int:event_id>/join')
    def do_join(event_id):
        ev = Event.query.get_or_404(event_id)
        name = request.form.get('name', '').strip()
        photo = request.files.get('photo')

        if not name:
            flash('Podaj imię.', 'danger')
            return redirect(url_for('join', event_id=ev.id))

        photo_path = None
        if photo and photo.filename:
            ext = os.path.splitext(photo.filename)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                flash('Dozwolone formaty: JPG, PNG, WEBP.', 'danger')
                return redirect(url_for('join', event_id=ev.id))
            fname = f'{uuid.uuid4().hex}{ext}'
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], fname)
            photo.save(save_path)
            _fix_image_orientation(save_path)
            photo_path = f'/static/uploads/{fname}'

        user = User(event_id=ev.id, name=name, photo_path=photo_path)
        db.session.add(user)
        db.session.commit()

        _set_current_user_id_for_event(ev.id, user.id)
        return redirect(url_for('wait', event_id=ev.id))

    # --- ekran oczekiwania przed głosowaniem ---
    @app.get('/e/<int:event_id>/wait')
    def wait(event_id):
        ev = Event.query.get_or_404(event_id)
        return render_template('wait.html', event=ev)

    @app.get('/e/<int:event_id>/status')
    def wait_status(event_id):
        ev = Event.query.get_or_404(event_id)
        joined = User.query.filter_by(event_id=ev.id).count()
        expected = ev.expected_players
        players = [u.name for u in User.query.filter_by(event_id=ev.id).all()]
        votes = Vote.query.filter_by(event_id=ev.id).count()

        # automatycznie otwórz głosowanie, gdy wszyscy są
        if not ev.is_voting_open and expected > 0 and joined >= expected:
            ev.is_voting_open = True
            db.session.commit()

        return jsonify({
            'joined': joined,
            'expected': expected,
            'players': players,
            'votes': votes,
            'open': ev.is_voting_open
        })

    # --- głosowanie ---
    @app.get('/e/<int:event_id>/vote')
    def vote(event_id):
        ev = Event.query.get_or_404(event_id)
        me_id = _get_current_user_id_for_event(ev.id)
        if not me_id:
            return redirect(url_for('join', event_id=ev.id))

        me = User.query.get_or_404(me_id)
        has_voted = Vote.query.filter_by(voter_user_id=me.id).first() is not None
        candidates = User.query.filter(User.event_id == ev.id, User.id != me.id).all()
        return render_template('vote.html', me=me, candidates=candidates, event=ev, has_voted=has_voted)

    @app.post('/e/<int:event_id>/vote')
    def do_vote(event_id):
        ev = Event.query.get_or_404(event_id)
        me_id = _get_current_user_id_for_event(ev.id)
        if not me_id:
            return redirect(url_for('join', event_id=ev.id))
        me = User.query.get_or_404(me_id)

        if Vote.query.filter_by(voter_user_id=me.id).first():
            return redirect(url_for('results', event_id=ev.id))

        try:
            candidate_id = int(request.form.get('candidate_id'))
        except:
            return redirect(url_for('vote', event_id=ev.id))

        if candidate_id == me.id:
            return redirect(url_for('vote', event_id=ev.id))

        candidate = User.query.filter_by(id=candidate_id, event_id=ev.id).first()
        if not candidate:
            return redirect(url_for('vote', event_id=ev.id))

        v = Vote(event_id=ev.id, voter_user_id=me.id, candidate_user_id=candidate.id)
        db.session.add(v)
        db.session.commit()

        return redirect(url_for('results', event_id=ev.id))

    # --- wyniki (z ekranem oczekiwania) ---
    @app.get('/results/<int:event_id>')
    def results(event_id):
        ev = Event.query.get_or_404(event_id)
        total_users = User.query.filter_by(event_id=ev.id).count()
        total_votes = Vote.query.filter_by(event_id=ev.id).count()

        # jeśli nie wszyscy zagłosowali -> ekran oczekiwania na wyniki
        if total_users == 0 or total_votes < total_users:
            remaining = max(total_users - total_votes, 0)
            return render_template(
                'waiting_results.html',
                event=ev,
                total_users=total_users,
                total_votes=total_votes,
                remaining=remaining
            )

        # dopiero tu faktyczne wyniki
        rows = db.session.execute(db.text("""
                                          SELECT u.id         AS user_id,
                                                 u.name       AS name,
                                                 u.photo_path AS photo_path,
                                                 COUNT(v.id)  AS votes
                                          FROM user u
            LEFT JOIN vote v ON v.candidate_user_id = u.id
                                          WHERE u.event_id = :eid
                                          GROUP BY u.id, u.name, u.photo_path
                                          ORDER BY votes DESC, name ASC
        """), {'eid': ev.id}).mappings().all()

        me_id = _get_current_user_id_for_event(ev.id)

        return render_template(
            'results.html',
            event=ev,
            rows=rows,
            total_voters=total_users,
            total_votes=total_votes,
            me_id=me_id
        )

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
