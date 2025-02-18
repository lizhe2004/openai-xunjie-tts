import asyncio
import tempfile
import subprocess
import os
from pathlib import Path
import re
import json
from datetime import datetime
import logging
from mutagen.mp3 import MP3
# from mutagen.id3 import TIT2
from mutagen.easyid3 import EasyID3
import shutil
import time
from xunjie_tts.xunjie_client import XunjieClient

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Language default (environment variable)

# Default speed from .env
DEFAULT_SPEED = int(os.getenv('DEFAULT_SPEED', '5'))
DEFAULT_VOLUME= int(os.getenv('DEFAULT_VOLUME', '5'))
DEFAULT_PITCH = int(os.getenv('DEFAULT_PITCH', '5'))

# Default output directory for saved files
DEFAULT_OUTPUT_DIR = os.getenv('TTS_OUTPUT_DIR', 'tts_output')

# Ensure the output directory exists
os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)

# Track temporary file names
TEMP_FILES = set()

# Function to load voice mappings from a JSON file
def load_voice_mappings(filepath='voice_mappings.json'):
    try:
        with open(filepath, 'r') as f:
            mappings = json.load(f)
            logging.info(f"Loaded voice mappings from {filepath}")
            return mappings
    except FileNotFoundError:
        logging.warning(f"{filepath} not found. Using default voice mappings.")
        return {}
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON in {filepath}: {e}. Using default voice mappings.")
        return {}

# Load voice mappings on startup
voice_mapping = load_voice_mappings()

def is_ffmpeg_installed():
    """Check if FFmpeg is installed and accessible."""
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def parse_voice_string(voice_string):
    """
    Parses the voice string to extract voice name, rate, and pitch adjustments.
    The voice string is in the format of:
    voice_name[-rate][-pitch][-volume]
    """

    match = re.match(r"([a-zA-Z0-9_]+)(?:[-](\d+))?(?:[-](\d+))?(?:[-](\d+))?", voice_string)

    if not match:
        logging.warning(f"Invalid voice string format: {voice_string}")
        return voice_string, None, None

    base_voice = match.group(1)
    rate_str = match.group(2)
    pitch_str = match.group(3)
    volume_str = match.group(4)

    rate = None
    pitch = None
    volume = None

    if rate_str:
        rate = int(rate_str)
        if not    rate <= 10:  # Basic rate validation
            logging.warning(f"Rate adjustment {rate} outside of reasonable bounds for: {voice_string}. Ignoring rate adjustment.")
            rate = None

    if pitch_str:
        pitch = int(pitch_str)
        if not pitch <= 10:  # Basic pitch validation
            logging.warning(f"Pitch adjustment {pitch} outside of reasonable bounds for: {voice_string}. Ignoring pitch adjustment.")
            pitch = None

    if volume_str:
        volume = int(volume_str)
        if not volume <= 10:  # Basic volume validation
            logging.warning(f"Volume adjustment {volume} outside of reasonable bounds for: {voice_string}. Ignoring volume adjustment.")
            volume = None

    logging.debug(f"Parsed voice string: {voice_string} -> base_voice: {base_voice}, rate_change: {rate}, pitch_change: {pitch}, volume: {volume}")
    return base_voice, rate, pitch, volume

async def _delayed_cleanup(file_path, retries=3, delay=30):
    """Deletes a temporary file with retries."""
    for attempt in range(retries):
        try:
            await asyncio.sleep(delay)
            Path(file_path).unlink(missing_ok=True)
            TEMP_FILES.discard(file_path)  # Remove from tracking
            logging.debug(f"Deleted temporary file: {file_path} after {attempt+1} attempts")
            return
        except Exception as e:
            logging.error(f"Error deleting temp file: {file_path}, attempt {attempt+1}: {e}")
    logging.error(f"Failed to delete temp file: {file_path} after {retries} attempts.")

async def _save_audio_file(temp_file_path, text, edge_tts_voice, response_format, save_output=False, converted_file=False):
    """Saves the audio file, handles metadata, and cleans up temp files."""
    output_filename = None
    if not save_output:
        return temp_file_path
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if converted_file:
            output_filename = os.path.join(DEFAULT_OUTPUT_DIR, f"{edge_tts_voice.replace('-', '_')}_{timestamp}.{response_format}")
        else:
            output_filename = os.path.join(DEFAULT_OUTPUT_DIR, f"{edge_tts_voice.replace('-', '_')}_{timestamp}.mp3")

        # Copy the temp file and save it
        try:
            shutil.copy2(temp_file_path, output_filename)
            logging.debug(f"Copied temp file to: {output_filename}")
        except Exception as e:
            logging.error(f"Error copying temp file: {e}")
            return None

        # Add metadata to the copy
        if response_format == "mp3" and not converted_file:
            try:
                audio = MP3(output_filename, ID3=EasyID3)
                audio["title"] = text
                audio.save()
                logging.debug(f"Embedded text as title metadata in: {output_filename}")
            except Exception as e:
                logging.error(f"Error embedding metadata in {output_filename}: {e}")

        logging.info(f"Saved audio file to: {output_filename}")
        return output_filename
    except Exception as e:
        logging.error(f"Error saving audio file: {e}")
        return None
    finally:
         asyncio.create_task(_delayed_cleanup(temp_file_path))

async def _generate_audio(api_key,text, voice, response_format, default_speed):
    """Generate TTS audio with dynamic rate and pitch adjustments."""
    logging.info(f"Generating audio for text: '{text[:50]}...', voice: {voice}, format: {response_format}, default_speed: {default_speed}")

    save_output = False
    if voice.endswith('+s'):
        save_output = True
        voice = voice[:-2]  # Remove the '+s' flag
        logging.debug(f"Save output flag is set for voice: {voice}")

    # Check for voice mapping
    base_voice_name = voice_mapping.get(voice, voice)

    # Parse the voice string for adjustments
    xunjie_tts_voice, rate, pitch, volume = parse_voice_string(base_voice_name)
    emotion = "neutral"
    if pitch is None:
       pitch =DEFAULT_PITCH

    if rate is None:
        rate =default_speed

    if volume is None:
        volume = DEFAULT_VOLUME


    temp_output_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    TEMP_FILES.add(temp_output_file.name)


    try:
        client = XunjieClient(
            text=text,
            voice=xunjie_tts_voice,
            rate=rate,
            pitch=pitch,
            volume=volume,
            device_id=api_key,
            token=api_key,
            emotion=emotion
        )
        logging.debug(f"xunjie-tts client initialized with voice: {xunjie_tts_voice}, rate: {rate}, pitch: {pitch}, volume: {volume}")
        await client.save(temp_output_file.name)
        logging.info(f"Successfully generated audio to temporary file: {temp_output_file.name}")

        if response_format == "mp3":
            if save_output:
                asyncio.create_task(_save_audio_file(temp_output_file.name, text, xunjie_tts_voice, response_format, save_output))
                return temp_output_file.name
            else:
                return temp_output_file.name

        if not is_ffmpeg_installed():
            logging.warning("FFmpeg is not available. Returning unmodified mp3 file.")
            return temp_output_file.name

        converted_output_file = tempfile.NamedTemporaryFile(delete=False, suffix=f".{response_format}")
        TEMP_FILES.add(converted_output_file.name)

        ffmpeg_command = [
            "ffmpeg",
            "-i", temp_output_file.name,
            "-c:a", {
                "aac": "aac",
                "mp3": "libmp3lame",
                "wav": "pcm_s16le",
                "opus": "libopus",
                "flac": "flac"
            }.get(response_format, "aac"),
            "-b:a", "192k" if response_format != "wav" else None,
            "-f", {
                "aac": "mp4",
                "mp3": "mp3",
                "wav": "wav",
                "opus": "ogg",
                "flac": "flac"
            }.get(response_format, response_format),
            "-y",
            converted_output_file.name
        ]

        try:
            logging.debug(f"Running FFmpeg command: {' '.join(ffmpeg_command)}")
            subprocess.run(ffmpeg_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logging.info(f"Successfully converted audio to: {response_format}")
        except subprocess.CalledProcessError as e:
            logging.error(f"FFmpeg error during audio conversion: {e.stderr.decode()}")
            raise RuntimeError(f"FFmpeg error during audio conversion: {e}")

        if save_output:
            asyncio.create_task(_save_audio_file(converted_output_file.name, text, xunjie_tts_voice, response_format, save_output, converted_file=True))
            return converted_output_file.name
        else:
            return converted_output_file.name

    except Exception as e:
        logging.error(f"Error during TTS generation: {e}",stack_info=True)
        if temp_output_file and temp_output_file.name in TEMP_FILES:
            TEMP_FILES.discard(temp_output_file.name)
        raise

def generate_speech(api_key,text, voice, response_format, speed):
    """同步版本的 generate_speech"""
    try:
        # 获取当前事件循环
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # 如果没有事件循环，创建一个新的
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # 如果循环正在运行，使用 run_coroutine_threadsafe
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(lambda: asyncio.run(_generate_audio(api_key,text, voice, response_format, speed)))
                return future.result()
        else:
            # 如果循环没有运行，直接运行
            return loop.run_until_complete(_generate_audio(api_key,text, voice, response_format, speed))
            
    except Exception as e:
        logging.error(f"Error in generate_speech: {e}",stack_info=True)
        return None

def get_models():
    return [
        {"id": "tts-1", "name": "Text-to-speech v1"},
        {"id": "tts-1-hd", "name": "Text-to-speech v1 HD"}
    ]

async def get_voices(language=None):
    return []
    # try:
    #     all_voices = await edge_tts.list_voices()

    #     filtered_voices = [
    #         {"name": v['ShortName'], "gender": v['Gender'], "language": v['Locale']}
    #         for v in all_voices if language == 'all' or language is None or v['Locale'] == language
    #     ]
    #     return filtered_voices
    # except Exception as e:
    #     logging.error(f"Error retrieving voices from edge-tts: {e}")
    #     return []



# def speed_to_rate(speed: float) -> str:
#     """
#     Converts a multiplicative speed value to the edge-tts "rate" format.

#     Args:
#         speed (float): The multiplicative speed value (e.g., 1.5 for +50%, 0.5 for -50%).

#     Returns:
#         str: The formatted "rate" string (e.g., "+50%" or "-50%").
#     """
#     percentage_change = (speed - 1) * 100
#     return f"{percentage_change:+.0f}%"

# Purge temp files on startup
for file_path in list(TEMP_FILES):
    try:
        Path(file_path).unlink(missing_ok=True)
        TEMP_FILES.discard(file_path)
        logging.info(f"Purged temp file on startup: {file_path}")
    except Exception as e:
        logging.error(f"Error purging temp file on startup: {file_path}: {e}")


# Example usage (you would integrate this into your API endpoint logic)
if __name__ == "__main__":
    async def test_speech_generation():
        text = "这是一个测试文本，用来测试语音合成效果。"  # 改用中文测试文本更合适

        # 测试用例
        voices_to_test = [
            # "siqi",                # 基础测试
            # "siqi-4",             # 测试语速
            # "siqi-4-6",           # 测试语速和音调
            # "siqi-4-5-7",         # 测试语速、音调和音量
            # "siqi+s",             # 测试保存功能
            # "invalid_voice",      # 测试无效语音
            # "aiting",
            "zhifeng_emo"
        ]

        api_key = "9993afb542febd941a7e7c6fe607"
        # 创建测试用的 voice_mappings.json
        sample_mappings = {
            'siqi': 'siqi',       # 直接映射
            'custom': 'siqi-5-5-5' # 自定义配置
        }
        
        # 确保测试目录存在
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        
        with open('voice_mappings.json', 'w', encoding='utf-8') as f:
            json.dump(sample_mappings, f, indent=4, ensure_ascii=False)

        for voice in voices_to_test:
            try:
                print(f"\n开始测试语音: {voice}")
                print(f"参数配置: 文本长度={len(text)}, 格式=mp3, 默认语速={DEFAULT_SPEED}")
                
                output_file = generate_speech(api_key,text, voice, "mp3", DEFAULT_SPEED)
                
                if output_file:
                    file_size = os.path.getsize(output_file)
                    print(f"生成成功: {output_file}")
                    print(f"文件大小: {file_size/1024:.2f}KB")
                else:
                    print(f"生成失败: {voice}")
            except Exception as e:
                print(f"测试出错: {voice}, 错误信息: {str(e)}")
            finally:
                print("-" * 50)

        print("\n测试完成!")

    # 运行测试
    asyncio.run(test_speech_generation())
