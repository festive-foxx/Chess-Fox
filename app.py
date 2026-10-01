import os
import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, emit

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'chess_secret_key_123'

# SocketIO uses simple-websocket in production
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory database to store active game rooms
rooms = {}

def generate_room_code(length=6):
    """Generates a random 6-character uppercase room code (e.g., 'A8X9K2')."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@app.route('/')
def index():
    """Serves the main HTML webpage to visitors."""
    return render_template('index.html')

@socketio.on('create_room')
def handle_create_room():
    """Handles room creation for Player 1 (White)."""
    room_code = generate_room_code()
    join_room(room_code)
    
    rooms[room_code] = {
        'players': [request.sid]
    }
    
    emit('room_created', {'room_code': room_code, 'color': 'white'})

@socketio.on('join_room')
def handle_join_room(data):
    """Handles Player 2 (Black) joining an existing room."""
    room_code = data.get('room_code', '').strip().upper()
    
    if room_code not in rooms:
        emit('error_message', {'message': 'Room code does not exist.'})
        return

    if len(rooms[room_code]['players']) >= 2:
        emit('error_message', {'message': 'Room is full.'})
        return

    join_room(room_code)
    rooms[room_code]['players'].append(request.sid)
    
    emit('player_joined', {'room_code': room_code, 'color': 'black'}, room=request.sid)
    emit('game_start', {'message': 'Game started! White to move.'}, room=room_code)

@socketio.on('make_move')
def handle_make_move(data):
    """Relays chess moves between connected players in a room."""
    room_code = data.get('room_code')
    move = data.get('move')
    
    if room_code in rooms:
        emit('move_made', {'move': move}, room=room_code, include_self=False)

if __name__ == '__main__':
    # Retrieve dynamic port from environment or fallback to 5000 for local testing
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)