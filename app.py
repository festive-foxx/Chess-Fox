import time
import random
import string
from flask import Flask, render_template, request, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import chess

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fox-chess-secret-key-123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# In-memory data stores
rooms = {}  # Format: { room_code: { 'board': chess.Board(), 'players': [], 'spectators': [], 'last_activity': timestamp } }
users = {}  # Format: { username: { 'password': pw, 'wins': 0, 'losses': 0, 'draws': 0 } }

# -------------------------------------------------------------
# CONFIGURATION VARIABLES
# -------------------------------------------------------------
INACTIVITY_LIMIT_SECONDS = 600  # 10 minutes in seconds
CHECK_INTERVAL_SECONDS = 60      # Check for expired rooms every 60 seconds


def generate_room_code():
    """Generates a unique 6-character uppercase room code."""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in rooms:
            return code


def get_public_game_list():
    """Formats active room data for display in the frontend lobby."""
    game_list = []
    for code, data in rooms.items():
        game_list.append({
            'code': code,
            'player_count': len(data['players']),
            'spectator_count': len(data.get('spectators', [])),
            'status': 'Waiting for Player' if len(data['players']) < 2 else 'In Progress'
        })
    return game_list


def get_room_state(room_code):
    """Returns a compact public snapshot of the room state for the frontend."""
    room = rooms.get(room_code)
    if room is None:
        return None

    board = room['board']
    return {
        'room_code': room_code,
        'fen': board.fen(),
        'turn': 'white' if board.turn == chess.WHITE else 'black',
        'game_over': board.is_game_over(),
        'in_check': board.is_check(),
        'status_message': get_game_status_message(room_code)
    }


def get_game_status_message(room_code):
    """Human-readable chess status for the current room."""
    room = rooms.get(room_code)
    if room is None:
        return 'Room no longer exists.'

    board = room['board']
    if board.is_checkmate():
        winner = 'black' if board.turn == chess.WHITE else 'white'
        return f'Checkmate — {winner} wins.'
    if board.is_stalemate():
        return 'Stalemate — draw.'
    if board.is_insufficient_material():
        return 'Draw by insufficient material.'
    if board.is_seventyfive_moves():
        return 'Draw by the 75-move rule.'
    if board.is_fivefold_repetition():
        return 'Draw by repetition.'
    if board.is_check():
        return f'Check — {"white" if board.turn == chess.WHITE else "black"} to move.'
    return f'{"white" if board.turn == chess.WHITE else "black"} to move.'


def emit_room_state(room_code):
    """Broadcasts the latest room snapshot to all room participants."""
    state = get_room_state(room_code)
    if state is not None:
        socketio.emit('room_state', state, room=room_code)


def remove_socket_from_room(sid, room_code=None):
    """Removes a socket from its room and clears empty rooms."""
    if room_code is None:
        for code, room in list(rooms.items()):
            if sid in room.get('players', []) or sid in room.get('spectators', []):
                room_code = code
                break

    if room_code is None or room_code not in rooms:
        return

    room = rooms[room_code]
    if sid in room.get('players', []):
        room['players'].remove(sid)
        room.get('player_colors', {}).pop(sid, None)
    if sid in room.get('spectators', []):
        room['spectators'].remove(sid)

    leave_room(room_code, sid)
    room['last_activity'] = time.time()

    if not room['players'] and not room.get('spectators', []):
        del rooms[room_code]
        print(f"[ROOM] Empty room '{room_code}' removed.")


# -------------------------------------------------------------
# INACTIVITY CLEANUP BACKGROUND WORKER
# -------------------------------------------------------------
def cleanup_inactive_rooms():
    """
    Background worker that runs continuously.
    Scans active rooms and removes any room inactive for longer than INACTIVITY_LIMIT_SECONDS.
    """
    while True:
        socketio.sleep(CHECK_INTERVAL_SECONDS)
        current_time = time.time()
        expired_rooms = []

        # Find rooms that exceed inactivity limit
        for room_code, room_data in list(rooms.items()):
            time_idle = current_time - room_data.get('last_activity', current_time)
            if time_idle >= INACTIVITY_LIMIT_SECONDS:
                expired_rooms.append(room_code)

        # Delete expired rooms and update lobby
        if expired_rooms:
            for room_code in expired_rooms:
                del rooms[room_code]
                print(f"[CLEANUP] Room '{room_code}' removed due to 10+ minutes of inactivity.")

            # Broadcast updated match list to all connected players
            socketio.emit('game_list_updated', get_public_game_list())


# Start background cleanup task when server boots
socketio.start_background_task(cleanup_inactive_rooms)


# -------------------------------------------------------------
# ROUTES & HTTP ENDPOINTS
# -------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'message': 'Username and password required.'}), 400
    if username in users:
        return jsonify({'message': 'User already exists.'}), 400

    users[username] = {'password': password, 'wins': 0, 'losses': 0, 'draws': 0}
    session['username'] = username
    return jsonify({'message': 'Registered successfully!', 'user': {'username': username, **users[username]}})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')

    if username in users and users[username]['password'] == password:
        session['username'] = username
        return jsonify({'message': 'Login successful!', 'user': {'username': username, **users[username]}})
    
    return jsonify({'message': 'Invalid credentials.'}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return jsonify({'message': 'Logged out successfully.'})


@app.route('/api/user_info', methods=['GET'])
def user_info():
    username = session.get('username')
    if username and username in users:
        return jsonify({'logged_in': True, 'user': {'username': username, **users[username]}})
    return jsonify({'logged_in': False})


@app.route('/api/record_result', methods=['POST'])
def record_result():
    username = session.get('username')
    if not username or username not in users:
        return jsonify({'message': 'Not logged in.'}), 401

    result = (request.get_json() or {}).get('result')
    if result == 'win':
        users[username]['wins'] += 1
    elif result == 'loss':
        users[username]['losses'] += 1
    elif result == 'draw':
        users[username]['draws'] += 1

    return jsonify({'message': 'Result recorded.', 'user': {'username': username, **users[username]}})


# -------------------------------------------------------------
# SOCKET.IO REAL-TIME EVENT HANDLERS
# -------------------------------------------------------------
@socketio.on('connect')
def handle_connect():
    # Send existing public games to newly connected user
    emit('game_list_updated', get_public_game_list(), room=request.sid)


@socketio.on('disconnect')
def handle_disconnect():
    for room_code in list(rooms.keys()):
        remove_socket_from_room(request.sid, room_code)

    socketio.emit('game_list_updated', get_public_game_list())


@socketio.on('create_room')
def handle_create_room():
    room_code = generate_room_code()
    rooms[room_code] = {
        'board': chess.Board(),
        'players': [request.sid],
        'player_colors': {request.sid: 'white'},
        'spectators': [],
        'last_activity': time.time(),
        'game_over': False
    }
    join_room(room_code)

    emit('room_created', {'room_code': room_code, 'color': 'white'}, room=request.sid)
    emit_room_state(room_code)
    socketio.emit('game_list_updated', get_public_game_list())


@socketio.on('join_room')
def handle_join_room(data):
    room_code = (data or {}).get('room_code', '').upper()
    if room_code not in rooms:
        emit('error_message', {'message': 'Room not found.'})
        return

    room = rooms[room_code]
    if request.sid in room.get('players', []) or request.sid in room.get('spectators', []):
        return

    if len(room['players']) >= 2:
        emit('error_message', {'message': 'Room is full! You can spectate instead.'})
        return

    room['players'].append(request.sid)
    room['player_colors'][request.sid] = 'black'
    room['last_activity'] = time.time()
    join_room(room_code)

    emit('player_joined', {'room_code': room_code, 'color': 'black'}, room=request.sid)
    socketio.emit('game_start', {'message': f'Player 2 joined room {room_code}. Game started!'}, room=room_code)
    emit_room_state(room_code)
    socketio.emit('game_list_updated', get_public_game_list())


@socketio.on('spectate_room')
def handle_spectate_room(data):
    room_code = (data or {}).get('room_code', '').upper()
    if room_code not in rooms:
        emit('error_message', {'message': 'Room no longer exists.'})
        return

    room = rooms[room_code]
    if request.sid in room.get('players', []) or request.sid in room.get('spectators', []):
        return

    room.setdefault('spectators', []).append(request.sid)
    room['last_activity'] = time.time()
    join_room(room_code)

    emit('spectate_joined', {
        'room_code': room_code,
        'fen': room['board'].fen()
    }, room=request.sid)


@socketio.on('make_move')
def handle_make_move(data):
    room_code = (data or {}).get('room_code')
    move_data = (data or {}).get('move')

    if room_code not in rooms:
        return

    room = rooms[room_code]
    if request.sid not in room['players']:
        emit('error_message', {'message': 'Only active players can make moves.'}, room=request.sid)
        return

    player_color = room.get('player_colors', {}).get(request.sid)
    if player_color is None:
        emit('error_message', {'message': 'Player color not assigned.'}, room=request.sid)
        return

    board = room['board']
    if board.is_game_over():
        emit('error_message', {'message': 'Game is already over.'}, room=request.sid)
        return

    expected_turn = chess.WHITE if player_color == 'white' else chess.BLACK
    if board.turn != expected_turn:
        emit('error_message', {'message': "It's not your turn."}, room=request.sid)
        return

    if not isinstance(move_data, dict):
        emit('error_message', {'message': 'Invalid move payload.'}, room=request.sid)
        return

    from_square = move_data.get('from')
    to_square = move_data.get('to')
    if not from_square or not to_square:
        emit('error_message', {'message': 'Move is missing target squares.'}, room=request.sid)
        return

    promotion = move_data.get('promotion')
    if promotion is not None and str(promotion) not in {'q', 'r', 'b', 'n'}:
        emit('error_message', {'message': 'Invalid promotion choice.'}, room=request.sid)
        return

    try:
        uci = f"{from_square}{to_square}"
        if promotion:
            uci += str(promotion)
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError
        board.push(move)
    except Exception:
        emit('error_message', {'message': 'Illegal move.'}, room=request.sid)
        return

    room['last_activity'] = time.time()
    room['game_over'] = board.is_game_over()

    if board.is_game_over():
        emit('game_over', {
            'room_code': room_code,
            'message': get_game_status_message(room_code),
            'winner': 'white' if board.turn == chess.BLACK else 'black'
        }, room=room_code)

    emit('move_made', {'move': move_data, 'fen': board.fen()}, room=room_code, include_self=False)
    emit_room_state(room_code)


import os

if __name__ == '__main__':
    # Render assigns a dynamic port via the PORT environment variable.
    # We default to 5000 for local testing.
    port = int(os.environ.get('PORT', 5000))
    
    # host='0.0.0.0' allows external web traffic from Render's load balancer
    socketio.run(app, host='0.0.0.0', port=port, debug=False)