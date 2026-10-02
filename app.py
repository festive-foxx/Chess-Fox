import sqlite3
from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string

app = Flask(__name__)
app.secret_key = 'foxchess_secret_key_change_in_production'
socketio = SocketIO(app, cors_allowed_origins="*")

DATABASE = 'database.db'

# --- DATABASE SETUP ---
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0
            )
        ''')
        conn.commit()

init_db()

# --- MULTIPLAYER ROOM STORAGE ---
rooms = {}

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def get_public_room_list():
    room_list = []
    for code, room in rooms.items():
        room_list.append({
            'code': code,
            'player_count': len(room['players']),
            'spectator_count': len(room['spectators']),
            'status': 'In Progress' if len(room['players']) == 2 else 'Waiting for opponent'
        })
    return room_list

# --- HTTP ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

# --- ACCOUNT & STATS ENDPOINTS ---
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password required.'}), 400

    try:
        hashed_pw = generate_password_hash(password)
        with get_db() as conn:
            conn.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, hashed_pw))
            conn.commit()
        return jsonify({'success': True, 'message': 'Account created! You can now log in.'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Username already taken.'}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    with get_db() as conn:
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'username': user['username'],
                'wins': user['wins'],
                'losses': user['losses'],
                'draws': user['draws']
            }
        })
    return jsonify({'success': False, 'message': 'Invalid username or password.'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/user_info', methods=['GET'])
def user_info():
    if 'user_id' not in session:
        return jsonify({'logged_in': False})

    with get_db() as conn:
        user = conn.execute('SELECT id, username, wins, losses, draws FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    if user:
        return jsonify({
            'logged_in': True,
            'user': dict(user)
        })
    return jsonify({'logged_in': False})

@app.route('/api/record_result', methods=['POST'])
def record_result():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in.'}), 401

    data = request.get_json() or {}
    result = data.get('result') # 'win', 'loss', or 'draw'

    if result not in ['win', 'loss', 'draw']:
        return jsonify({'success': False, 'message': 'Invalid result type.'}), 400

    col = 'wins' if result == 'win' else ('losses' if result == 'loss' else 'draws')

    with get_db() as conn:
        conn.execute(f'UPDATE users SET {col} = {col} + 1 WHERE id = ?', (session['user_id'],))
        conn.commit()

    return jsonify({'success': True})

# --- SOCKET.IO EVENTS ---
@socketio.on('connect')
def handle_connect():
    emit('game_list_updated', get_public_room_list())

@socketio.on('create_room')
def handle_create_room():
    room_code = generate_room_code()
    rooms[room_code] = {
        'players': {request.sid: 'white'},
        'spectators': [],
        'fen': 'start'
    }
    join_room(room_code)
    emit('room_created', {'room_code': room_code, 'color': 'white'})
    socketio.emit('game_list_updated', get_public_room_list())

@socketio.on('join_room')
def handle_join_room(data):
    room_code = data.get('room_code')
    if room_code in rooms:
        room = rooms[room_code]
        if len(room['players']) < 2:
            room['players'][request.sid] = 'black'
            join_room(room_code)
            emit('player_joined', {'room_code': room_code, 'color': 'black'})
            socketio.to(room_code).emit('game_start', {'message': 'Both players connected! Match started.'})
            socketio.emit('game_list_updated', get_public_room_list())
        else:
            emit('error_message', {'message': 'Room is full! You can spectate instead.'})
    else:
        emit('error_message', {'message': 'Room does not exist.'})

@socketio.on('spectate_room')
def handle_spectate_room(data):
    room_code = data.get('room_code')
    if room_code in rooms:
        join_room(room_code)
        rooms[room_code]['spectators'].append(request.sid)
        emit('spectate_joined', {
            'room_code': room_code,
            'fen': rooms[room_code]['fen']
        })
        socketio.emit('game_list_updated', get_public_room_list())

@socketio.on('make_move')
def handle_make_move(data):
    room_code = data.get('room_code')
    if room_code in rooms:
        rooms[room_code]['fen'] = data.get('fen')
        emit('move_made', data, to=room_code, include_self=False)

if __name__ == '__main__':
    socketio.run(app, debug=True)