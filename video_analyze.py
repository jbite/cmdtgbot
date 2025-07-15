import subprocess
import json
import datetime

def analyze_rtmp_video_stream(stream_url):
    """
    使用 ffprobe 分析 RTMP 視訊流並返回核心指標。
    
    Args:
        stream_url (str): RTMP 視訊流的 URL。
        
    Returns:
        dict: 包含核心視訊流指標的字典，如果失敗則返回 None。
    """
    # 構建 ffprobe 命令
    # -hide_banner: 隱藏 ffprobe 的版權信息
    # -loglevel error: 只顯示錯誤信息
    # -print_format json: 以 JSON 格式輸出結果
    # -show_streams: 顯示所有媒體流的資訊
    # -select_streams v:0: 只選擇第一個視頻流
    
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-loglevel", "error",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0", # 確保只獲取視頻流
        stream_url
    ]

    try:
        print(f"[{datetime.datetime.now()}] 正在嘗試分析流: {stream_url}...")
        # 執行命令，capture_output=True 捕獲標準輸出和錯誤，text=True 將輸出解碼為字符串
        # check=True 會在命令返回非零退出碼時拋出 CalledProcessError
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10) # 設置一個合理的小超時
        
        # 解析 JSON 輸出
        data = json.loads(result.stdout)
        
        metrics = {}

        # 提取視頻流資訊
        if "streams" in data and len(data["streams"]) > 0:
            video_stream = data["streams"][0] # 已經用 -select_streams v:0 選取了第一個視頻流
            
            metrics["video_codec"] = video_stream.get("codec_name")
            metrics["width"] = video_stream.get("width")
            metrics["height"] = video_stream.get("height")
            
            # 處理幀率，它可能是 "num/den" 格式
            r_frame_rate_str = video_stream.get("r_frame_rate")
            if r_frame_rate_str and '/' in r_frame_rate_str:
                num, den = map(int, r_frame_rate_str.split('/'))
                metrics["actual_fps"] = round(num / den, 2) if den != 0 else 0
            else: # 如果不是 num/den 格式，直接轉換為浮點數
                metrics["actual_fps"] = float(r_frame_rate_str) if r_frame_rate_str else None

            video_bit_rate = video_stream.get("bit_rate")
            metrics["video_bit_rate_mbps"] = round(int(video_bit_rate) / 1_000_000, 2) if video_bit_rate else None
            
            # 獲取音頻信息 (如果存在)
            audio_stream = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
            if audio_stream:
                metrics["audio_codec"] = audio_stream.get("codec_name")
                metrics["audio_bit_rate_kbps"] = round(int(audio_stream.get("bit_rate")) / 1_000, 2) if audio_stream.get("bit_rate") else None
                metrics["sample_rate"] = int(audio_stream.get("sample_rate")) if audio_stream.get("sample_rate") else None
                metrics["channels"] = int(audio_stream.get("channels")) if audio_stream.get("channels") else None
            else:
                metrics["audio_codec"] = "N/A"
        else:
            print(f"[{datetime.datetime.now()}] 警告: 未找到視頻流信息。")
            return None # 如果沒有視頻流，可能就是問題

        return metrics

    except FileNotFoundError:
        print(f"[{datetime.datetime.now()}] 錯誤: 未找到 ffprobe 命令。請確保 FFmpeg 已安裝且其路徑已添加到系統 PATH 中。")
        return None
    except subprocess.CalledProcessError as e:
        print(f"[{datetime.datetime.now()}] ffprobe 執行失敗。錯誤碼: {e.returncode}")
        print(f"Stderr: {e.stderr.strip()}") # 打印標準錯誤輸出，幫助診斷
        return None
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[{datetime.datetime.now()}] 無法解析 ffprobe 輸出為 JSON 或數據轉換錯誤: {e}")
        print(f"原始輸出:\n{result.stdout.strip()}")
        return None
    except subprocess.TimeoutExpired:
        print(f"[{datetime.datetime.now()}] ffprobe 超時，無法獲取流資訊。")
        return None
    except Exception as e:
        print(f"[{datetime.datetime.now()}] 發生未知錯誤: {e}")
        return None

# --- 腳本主執行部分 ---
if __name__ == "__main__":
    RTMP_STREAM_URL = None
    
    stream_data = analyze_rtmp_video_stream(RTMP_STREAM_URL)

    if stream_data:
        print("\n--- RTMP 視訊流核心指標 ---")
        for key, value in stream_data.items():
            print(f"{key.replace('_', ' ').capitalize()}: {value}")
    else:
        print("\n無法獲取視訊流的核心指標。")