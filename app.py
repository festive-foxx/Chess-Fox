import os
import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, leave_room, emit

# Initialize Flask application
app = Flask(__name__)
app.config['SECRET_KEY'] = 'fox_chess_secret_key_123'

# SocketIO setup with CORS enabled
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory database storing room state
# Structure: { room_code: { 'players': [sid_white, sid_black], 'spectators': [sid1, ...], 'fen': str, 'history': list, 'status': str } }
rooms = {}

def generate_room_code(length=6):
    """Generates a unique 6-character uppercase room code (e.g., 'FX89A2')."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def get_public_games():
    """Formats room data into a clean list for the public lobby UI."""
    public_list = []
    for code, room in rooms.items():
        public_list.append({
            'code': code,
            'player_count': len(room['players']),
            'spectator_count': len(room['spectators']),
            'status': room['status']
        })
    return public_list

def broadcast_game_list():
    """Broadcasts the latest room directory to all connected socket clients."""
    socketio.emit('game_list_updated', get_public_games())

@app.route('/')
def index():
    """Serves the main Fox Chess web interface."""
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    """Sends the current active games list as soon as a client connects."""
    emit('game_list_updated', get_public_games())

@socketio.on('create_room')
def handle_create_room():
    """Handles creating a new multiplayer room."""
    room_code = generate_room_code()
    join_room(room_code)
    
    rooms[room_code] = {
        'players': [request.sid],
        'spectators': [],
        'fen': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
        'history': [],
        'status': 'Waiting for Player 2'
    }
    
    emit('room_created', {'room_code': room_code, 'color': 'white'})
    broadcast_game_list()

@socketio.on('join_room')
def handle_join_room(data):
    """Handles Player 2 joining an existing match room."""
    room_code = data.get('room_code', '').strip().upper()
    
    if room_code not in rooms:
        emit('error_message', {'message': 'Room code does not exist.'})
        return

    if len(rooms[room_code]['players']) >= 2:
        emit('error_message', {'message': 'Room is full. Try spectating instead!'})
        return

    join_room(room_code)
    rooms[room_code]['players'].append(request.sid)
    rooms[room_code]['status'] = 'In Progress'
    
    emit('player_joined', {'room_code': room_code, 'color': 'black'}, room=request.sid)
    emit('game_start', {'message': 'Game started! White to move.'}, room=room_code)
    broadcast_game_list()

@socketio.on('spectate_room')
def handle_spectate_room(data):
    """Allows users to watch an active match as a spectator."""
    room_code = data.get('room_code', '').strip().upper()

    if room_code not in rooms:
        emit('error_message', {'message': 'Match no longer exists.'})
        return

    join_room(room_code)
    rooms[room_code]['spectators'].append(request.sid)

    # Emit current state so spectator instantly syncs with current board
    emit('spectate_joined', {
        'room_code': room_code,
        'fen': rooms[room_code]['fen'],
        'history': rooms[room_code]['history'],
        'status': rooms[room_code]['status']
    }, room=request.sid)

    broadcast_game_list()

@socketio.on('make_move')
def handle_make_move(data):
    """Relays move details and updates room state for players & spectators."""
    room_code = data.get('room_code')
    move = data.get('move')
    fen = data.get('fen')

    if room_code in rooms:
        rooms[room_code]['fen'] = fen
        if move:
            rooms[room_code]['history'].append(move)

        # Broadcast move to both opponent and all spectators in the room
        emit('move_made', {'move': move, 'fen': fen}, room=room_code, include_self=False)

@socketio.on('disconnect')
def handle_disconnect():
    """Cleans up empty rooms when players or spectators disconnect."""
    sid = request.sid
    rooms_to_delete = []

    for code, room in rooms.items():
        if sid in room['players']:
            room['players'].remove(sid)
            emit('error_message', {'message': 'A player disconnected.'}, room=code)
            if len(room['players']) == 0:
                rooms_to_delete.append(code)
        elif sid in room['spectators']:
            room['spectators'].remove(sid)

    for code in rooms_to_delete:
        del rooms[code]

    broadcast_game_list()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)