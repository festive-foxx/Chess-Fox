import random
import string
from flask import Flask, render_template, request
from flask_socketio import SocketIO, join_room, emit

# Initialize Flask web application and SocketIO for real-time communication
app = Flask(__name__)
app.config['SECRET_KEY'] = 'chess_secret_key_123'
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory database to store active room codes and player socket IDs
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
    """Triggered when Player 1 clicks 'Create Remote Room'."""
    room_code = generate_room_code()
    join_room(room_code)
    
    # Store room details: Player 1 gets assigned White
    rooms[room_code] = {
        'players': [request.sid]
    }
    
    # Send room code and assigned color back to Player 1
    emit('room_created', {'room_code': room_code, 'color': 'white'})

@socketio.on('join_room')
def handle_join_room(data):
    """Triggered when Player 2 enters a room code and clicks 'Join Room'."""
    room_code = data.get('room_code', '').strip().upper()
    
    # Validation checks
    if room_code not in rooms:
        emit('error_message', {'message': 'Room code does not exist.'})
        return

    if len(rooms[room_code]['players']) >= 2:
        emit('error_message', {'message': 'Room is full.'})
        return

    # Join the room: Player 2 gets assigned Black
    join_room(room_code)
    rooms[room_code]['players'].append(request.sid)
    
    emit('player_joined', {'room_code': room_code, 'color': 'black'}, room=request.sid)
    emit('game_start', {'message': 'Game started! White to move.'}, room=room_code)

@socketio.on('make_move')
def handle_make_move(data):
    """Broadcasts a player's move to their opponent in the same room."""
    room_code = data.get('room_code')
    move = data.get('move')
    
    if room_code in rooms:
        # Relay move to the other player in the room
        emit('move_made', {'move': move}, room=room_code, include_self=False)

if __name__ == '__main__':
    # Start server locally on port 5000
    socketio.run(app, debug=True)