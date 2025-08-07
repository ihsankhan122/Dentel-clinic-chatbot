import os
import pandas as pd
import sqlite3
import threading
import time
import logging
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from werkzeug.utils import secure_filename
from chatbot_model import get_chat_response

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'csv','db'}
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = '...'  # Required for session and flash messages

# Initialize DB
DB_FILE = 'chatbot_data.db'
conn = sqlite3.connect(DB_FILE)
conn.execute('''CREATE TABLE IF NOT EXISTS chat_history (id INTEGER PRIMARY KEY, message TEXT, response TEXT)''')
conn.execute('''CREATE TABLE IF NOT EXISTS current_file (id INTEGER PRIMARY KEY, filename TEXT)''')
conn.commit()
conn.close()

# Global variables for stop execution
stop_execution_flag = False
execution_lock = threading.Lock()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_current_file():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT filename FROM current_file ORDER BY id DESC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_current_file(filename):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM current_file")
    cursor.execute("INSERT INTO current_file (filename) VALUES (?)", (filename,))
    conn.commit()
    conn.close()

def get_session_history():
    """Get the recent 5 chat interactions from session"""
    if 'chat_history' not in session:
        session['chat_history'] = []
    return session['chat_history']

def add_to_session_history(user_message, bot_response):
    """Add a new chat interaction to session history, keeping only the last 5"""
    history = get_session_history()
    history.append((user_message, bot_response))
    # Keep only the last 5 interactions
    session['chat_history'] = history[-5:]

@app.route('/')
def index():
    current_file = get_current_file()
    # Get chat history from session
    session_history = get_session_history()
    return render_template('index.html', history=session_history, filename=current_file)

@app.route('/ask', methods=['POST'])
def ask():
    global stop_execution_flag
    
    # Reset stop flag at the beginning of each request
    with execution_lock:
        stop_execution_flag = False
    
    user_input = request.json.get('message')
    logger.info(f"Received user input: {user_input}")
    
    if not user_input or user_input.strip() == "":
        return jsonify({'response': 'Please enter a valid message.'})
    
    current_file = get_current_file()
    
    if not current_file:
        return jsonify({'response': '⚠️ No file uploaded. Please upload a CSV first.'})
    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], current_file)
    
    try:
        df = pd.read_csv(file_path)
        logger.info(f"Successfully loaded CSV file with {len(df)} rows")
    except Exception as e:
        logger.error(f"Error loading CSV file: {str(e)}")
        return jsonify({'response': f'Error loading CSV file: {str(e)}'})
    
    # Get session history to provide context
    session_history = get_session_history()
    logger.info(f"Session history contains {len(session_history)} interactions")
    
    # Check if execution was stopped before processing
    with execution_lock:
        if stop_execution_flag:
            return jsonify({'response': 'Request stopped by user.'})
    
    # Process the request with periodic checks for stop flag
    def process_with_stop_check():
        global stop_execution_flag
        
        # Simulate processing time - in a real app, this would be your actual processing
        # We'll break the processing into chunks to check for stop flag
        for i in range(10):  # Simulate 10 chunks of work
            time.sleep(0.5)  # Each chunk takes 0.5 seconds
            
            # Check if execution was stopped
            with execution_lock:
                if stop_execution_flag:
                    return None
        
        # If not stopped, get the actual response with session history context
        return get_chat_response(user_input, df, session_history)
    
    # Process the request
    response = process_with_stop_check()
    
    # If execution was stopped during processing
    if response is None:
        return jsonify({'response': 'Request stopped by user.'})
    
    # Check if response is empty
    if not response or response.strip() == "":
        logger.warning("Empty response received from get_chat_response")
        response = "I'm sorry, I couldn't generate a response. Please try again."
    
    # Add to session history
    add_to_session_history(user_input, response)
    logger.info(f"Added to session history: {user_input} -> {response[:50]}...")
    
    # Save to DB
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO chat_history (message, response) VALUES (?, ?)", (user_input, response))
        conn.commit()
        conn.close()
        logger.info("Saved to database")
    except Exception as e:
        logger.error(f"Error saving to database: {str(e)}")
    
    logger.info(f"Returning response: {response[:100]}...")
    return jsonify({'response': response})

@app.route('/stop_execution', methods=['POST'])
def stop_execution():
    global stop_execution_flag
    
    # Set the stop flag
    with execution_lock:
        stop_execution_flag = True
    
    logger.info("Execution stop requested")
    return jsonify({'status': 'stopped'})

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(url_for('index'))
    file = request.files['file']
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        set_current_file(filename)
        logger.info(f"Uploaded file: {filename}")
        
        # Clear chat history from session and DB
        session.pop('chat_history', None)
        conn = sqlite3.connect(DB_FILE)
        conn.execute("DELETE FROM chat_history")
        conn.commit()
        conn.close()
        
    return redirect(url_for('index'))

@app.route('/delete_file', methods=['POST'])
def delete_file():
    current_file = get_current_file()
    if current_file:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], current_file)
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Clear file + chat history from session and DB
        session.pop('chat_history', None)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM current_file")
        cursor.execute("DELETE FROM chat_history")
        conn.commit()
        conn.close()
        
        logger.info(f"Deleted file: {current_file}")
        
    return redirect(url_for('index'))

@app.route('/clear_chat', methods=['POST'])
def clear_chat():
    # Clear chat history from session and DB
    session.pop('chat_history', None)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM chat_history")
    conn.commit()
    conn.close()
    
    logger.info("Cleared chat history")
    return jsonify({'status': 'cleared'})

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)