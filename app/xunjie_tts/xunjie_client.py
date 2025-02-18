"""
Communicate package.
"""
import logging
import re
from typing import (
    Any,
    AsyncGenerator,
    ContextManager,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
    Union,
)
class XunjieClient:
    """
    Class for communicating with the service.
    """

    def __init__(
        self,
        device_id: str ,
        token: str ,
        text: str,
        voice: str = "Microsoft Server Speech Text to Speech Voice (en-US, AriaNeural)",
        *,
        rate: int = 4,
        volume: int = 4,
        pitch:  int = 4,
        receive_timeout: int = 5,
        emotion: str = "neutral"

    ):
        """
        Initializes the Client class.

        Raises:

            ValueError: If the voice is not valid.
        """
        if not isinstance(text, str):
            raise TypeError("text must be str")
        self.text: str = text
        self.device_id: str = device_id
        self.token: str = token
        self.rate: int = rate
        self.volume: int = volume
        self.pitch: int = pitch 
        self.emotion: str = emotion
     
        if not isinstance(voice, str):
            raise TypeError("voice must be str")
        self.voice: str = voice

        if not isinstance(receive_timeout, int):
            raise TypeError("receive_timeout must be int")
        self.receive_timeout: int = receive_timeout


    async def save(
        self,
        audio_fname: Union[str, bytes],
    ) -> str:
        """
        Generate audio from text using xunjie TTS API and save to file.
        
        Args:
            audio_fname: Path where the audio file should be saved
        """
        import aiohttp
        import asyncio
        
        # 验证输入参数
        if not self.text:
            raise ValueError("text cannot be empty")
            
        # 构建请求参数
        params = {
            "client": "web",
            "source": "335",
            "soft_version": "V4.4.0.0", 
            "device_id": self.device_id,
            "text": self.text,
            "bgid": 0,
            "bg_volume": 5,
            "format": "mp3",
            "voice": self.voice,
            "volume": self.volume,  
            "speech_rate": self.rate, 
            "pitch_rate": self.pitch, 
            "title": self.text[:10],  # 取前10个字符作为标题
            "token": self.token,
            "bg_url": "",
            "emotion": self.emotion
        }
        logging.info(f"Sending request to Xunjie TTS API with params: {params}")
        # 发送API请求
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://user.api.hudunsoft.com/v1/alivoice/texttoaudio",
                data=params,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                },
                timeout=self.receive_timeout
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"API request failed with status {response.status}")
                
                data = await response.json()
                
                # 处理任务ID的情况
                if data.get("code") == "2105" and data.get("data", {}).get("task_id"):
                    task_id = data["data"]["task_id"]
                    task_params = {
                        "client": "web",
                        "source": "335",
                        "soft_version": "V4.4.0.0",
                        "device_id": self.device_id,
                        "taskId": task_id
                    }
                    
                    # 轮询任务状态，最多等待60秒
                    for _ in range(12):  # 5秒一次，最多轮询12次
                        async with session.post(
                            "https://user.api.hudunsoft.com/v1/alivoice/textTaskInfo",
                            data=task_params,
                            headers={
                                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                            },
                            timeout=self.receive_timeout
                        ) as task_response:
                            task_data = await task_response.json()
                            if task_data.get("code") == 0:
                                result = task_data.get("data", {})
                                if result.get("is_complete"):
                                    file_link = result.get("file_link")
                                    if file_link:
                                        break
                            await asyncio.sleep(5)
                    else:
                        raise RuntimeError("Task timeout after 60 seconds")
                
                elif data.get("code") != 0:
                    raise RuntimeError(f"API error: {data.get('message', 'Unknown error')}")
                else:
                    # 直接返回文件链接的情况
                    result = data.get("data", {})
                    if not result.get("is_complete"):
                        raise RuntimeError("Audio generation not complete")
                    file_link = result.get("file_link")
                
                if not file_link:
                    raise RuntimeError("No file link in response")
                
                # 下载音频文件
                async with session.get(file_link) as audio_response:
                    if audio_response.status != 200:
                        raise RuntimeError(f"Failed to download audio file: {audio_response.status}")
                    
                    with open(audio_fname, 'wb') as f:
                        f.write(await audio_response.read())
                    
                return 
