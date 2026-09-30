import random
import string
from flask import Flask, render_template, request  # pyright: ignore[reportMissingImports]
from flask_socketio import SocketIO, join_room, leave_room, emit  # pyright: ignore[reportMissingImports,reportMissingModuleSource]

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chess_secret_key_123'
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory storage for active rooms
# Format: { room_code: { 'players': [sid1, sid2], 'fen': 'starting_fen' } }
rooms = {}

def generate_room_code(length=6):
    """Generates a random uppercase alphanumeric room code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@app.route('/')
def index():
    """Renders the main chess webpage."""
    return render_template('index.html')

@socketio.on('create_room')
def handle_create_room():
    """Generates a new room, assigns the creator as White, and joins the Socket.IO room."""
    room_code = generate_room_code()
    join_room(room_code)
    
    rooms[room_code] = {
        'players': [request.sid],
        'turn': 'w'
    }
    
    emit('room_created', {'room_code': room_code, 'color': 'white'})

@socketio.on('join_room')
def handle_join_room(data):
    """Joins an existing room if it has space, assigning the joiner as Black."""
    room_code = data.get('room_code', '').strip().upper()
    
    if room_code not in rooms:
        emit('error_message', {'message': 'Room code does not exist.'})
        return

    if len(rooms[room_code]['players']) >= 2:
        emit('error_message', {'message': 'Room is already full.'})
        return

    join_room(room_code)
    rooms[room_code]['players'].append(request.sid)
    
    # Notify joiner of their assignment
    emit('player_joined', {'room_code': room_code, 'color': 'black'}, room=request.sid)
    # Notify both players that the game can start
    emit('game_start', {'message': 'Game started! White to move.'}, room=room_code)

@socketio.on('make_move')
def handle_make_move(data):
    """Relays a move to the opponent in the room."""
    room_code = data.get('room_code')
    move = data.get('move')  # Object containing 'from', 'to', and optional 'promotion'
    
    if room_code in rooms:
        # Broadcast move to the opponent
        emit('move_made', {'move': move}, room=room_code, include_self=False)

if __name__ == '__main__':
    socketio.run(app, debug=True)