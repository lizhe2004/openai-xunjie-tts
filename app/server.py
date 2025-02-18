# server.py

from flask import Flask, request, send_file, jsonify
from gevent.pywsgi import WSGIServer
from dotenv import load_dotenv
import os

from handle_text import prepare_tts_input_with_context
from tts_handler import generate_speech, get_models, get_voices
from utils import getenv_bool, AUDIO_FORMAT_MIME_TYPES

app = Flask(__name__)
load_dotenv()

API_KEY = os.getenv('API_KEY', 'your_api_key_here')
PORT = int(os.getenv('PORT', 5050))

DEFAULT_VOICE = os.getenv('DEFAULT_VOICE', 'siqi')
DEFAULT_RESPONSE_FORMAT = os.getenv('DEFAULT_RESPONSE_FORMAT', 'mp3')
DEFAULT_SPEED = float(os.getenv('DEFAULT_SPEED',4))

REMOVE_FILTER = getenv_bool('REMOVE_FILTER', False)
EXPAND_API = getenv_bool('EXPAND_API', True)

# DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'tts-1')

@app.route('/v1/audio/speech', methods=['POST'])
@app.route('/audio/speech', methods=['POST'])  # Add this line for the alias
def text_to_speech():
    data = request.json
    if not data or 'input' not in data:
        return jsonify({"error": "Missing 'input' in request body"}), 400
    text = data.get('input')
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing API key in Authorization header"}), 401
    
    api_key = auth_header.split('Bearer ')[1]
    
    if not REMOVE_FILTER:
        text = prepare_tts_input_with_context(text)

    # model = data.get('model', DEFAULT_MODEL)
    voice = data.get('voice', DEFAULT_VOICE)

    response_format = data.get('response_format', DEFAULT_RESPONSE_FORMAT)
    speed = float(data.get('speed', DEFAULT_SPEED))
    
    mime_type = AUDIO_FORMAT_MIME_TYPES.get(response_format, "audio/mpeg")

    # Generate the audio file in the specified format with speed adjustment
    output_file_path = generate_speech(api_key,text, voice, response_format, speed)

    # Return the file with the correct MIME type
    return send_file(output_file_path, mimetype=mime_type, as_attachment=True, download_name=f"speech.{response_format}")

# @app.route('/v1/models', methods=['GET', 'POST'])
# @app.route('/models', methods=['GET', 'POST'])
# def list_models():
#     return jsonify({"data": get_models()})

# @app.route('/v1/voices', methods=['GET', 'POST'])
# @app.route('/voices', methods=['GET', 'POST'])
# def list_voices():
#     specific_language = None

#     data = request.args if request.method == 'GET' else request.json
#     if data and ('language' in data or 'locale' in data):
#         specific_language = data.get('language') if 'language' in data else data.get('locale')

#     return jsonify({"voices": get_voices(specific_language)})

# @app.route('/v1/voices/all', methods=['GET', 'POST'])
# @app.route('/voices/all', methods=['GET', 'POST'])
# @require_api_key
# def list_all_voices():
#     return jsonify({"voices": get_voices('all')})


if __name__ == '__main__':
    http_server = WSGIServer(('0.0.0.0', PORT), app)
    http_server.serve_forever()
