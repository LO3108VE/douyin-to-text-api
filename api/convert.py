from flask import Flask, request, jsonify
import requests
import json
import time
import tempfile
import os
import openai

app = Flask(__name__)

# 从环境变量获取配置信息
FREECONVERT_API_KEY = os.environ.get('FREECONVERT_API_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY') 
XIAZAITOOL_TOKEN = os.environ.get('XIAZAITOOL_TOKEN')

# 设置OpenAI API Key
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

def extract_video_url(douyin_url):
    """从抖音链接解析出真实视频URL"""
    url = "https://www.xiazaitool.com/api/parseVideoUrl"
    payload = {
        "url": douyin_url,
        "token": XIAZAITOOL_TOKEN
    }
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            
            if 'data' in result and 'videoUrls' in result['data']:
                return result['data']['videoUrls']
            else:
                return None
        else:
            return None
            
    except Exception as e:
        return None

def convert_video_to_audio(video_url):
    """将视频转换为音频"""
    input_body = {
        "tasks": {
            "import-1": {
                "operation": "import/url",
                "url": video_url,
                "filename": "input_video"
            },
            "convert-1": {
                "operation": "convert",
                "input": "import-1",
                "input_format": "mp4",
                "output_format": "mp3",
                "options": {
                    "audio_filter_reverse": False
                }
            },
            "export-1": {
                "operation": "export/url",
                "input": [
                    "convert-1"
                ],
                "filename": "converted_audio"
            }
        }
    }

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {FREECONVERT_API_KEY}'
    }

    url = "https://api.freeconvert.com/v1/process/jobs"

    try:
        response = requests.post(url, data=json.dumps(input_body), headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            response_json = response.json()
            
            if 'id' in response_json:
                job_id = response_json['id']
                download_url = wait_for_completion_and_get_url(job_id)
                return download_url
            else:
                return None
        else:
            return None
                
    except Exception as e:
        return None

def wait_for_completion_and_get_url(job_id, max_wait_time=300):
    """等待任务完成并返回下载链接"""
    headers = {
        'Authorization': f'Bearer {FREECONVERT_API_KEY}',
        'Accept': 'application/json'
    }
    
    status_url = f"https://api.freeconvert.com/v1/process/jobs/{job_id}"
    
    start_time = time.time()
    while time.time() - start_time < max_wait_time:
        try:
            response = requests.get(status_url, headers=headers)
            if response.status_code == 200:
                status_json = response.json()
                status = status_json.get('status', 'unknown')
                
                if status == 'completed':
                    tasks = status_json.get('tasks', [])
                    for task_info in tasks:
                        if task_info.get('operation') == 'export/url' and task_info.get('status') == 'completed':
                            result = task_info.get('result', {})
                            if 'url' in result:
                                return result['url']
                    return None
                        
                elif status == 'failed':
                    return None
                    
                elif status in ['processing', 'queued', 'pending']:
                    time.sleep(5)
                    continue
                    
            else:
                return None
                
        except Exception as e:
            time.sleep(5)
            continue
    
    return None

def transcribe_audio_to_text(audio_url):
    """将音频转换为文字"""
    try:
        # 下载音频文件
        audio_response = requests.get(audio_url, timeout=60)
        if audio_response.status_code != 200:
            return None
        
        audio_data = audio_response.content
        
        # 保存为临时文件
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_data)
            temp_file_path = f.name
        
        # 调用Whisper API识别
        try:
            with open(temp_file_path, "rb") as audio_file:
                response = openai.Audio.transcribe(
                    model="whisper-1",
                    file=audio_file,
                    language="zh"
                )
            
            transcribed_text = response["text"]
            return transcribed_text
            
        except Exception as e:
            return None
            
        finally:
            # 清理临时文件
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        return None

@app.route('/api/convert', methods=['POST'])
def convert_douyin_to_text():
    """API端点：抖音视频转文字"""
    try:
        # 检查必要的环境变量
        if not all([FREECONVERT_API_KEY, OPENAI_API_KEY, XIAZAITOOL_TOKEN]):
            return jsonify({
                'error': '服务配置不完整，请联系管理员',
                'success': False
            }), 500
        
        # 获取请求数据
        data = request.get_json()
        if not data or 'douyin_url' not in data:
            return jsonify({
                'error': '请提供douyin_url参数',
                'success': False
            }), 400
        
        douyin_url = data['douyin_url'].strip()
        if not douyin_url:
            return jsonify({
                'error': '抖音链接不能为空',
                'success': False
            }), 400
        
        # 步骤1: 解析抖音链接
        video_url = extract_video_url(douyin_url)
        if not video_url:
            return jsonify({
                'error': '无法解析抖音视频链接，请检查链接是否正确',
                'success': False
            }), 400
        
        # 步骤2: 转换视频为音频
        audio_url = convert_video_to_audio(video_url)
        if not audio_url:
            return jsonify({
                'error': '视频转音频失败，请稍后重试',
                'success': False
            }), 500
        
        # 步骤3: 音频转文字
        transcribed_text = transcribe_audio_to_text(audio_url)
        if not transcribed_text:
            return jsonify({
                'error': '语音识别失败，请确保视频包含清晰的语音内容',
                'success': False
            }), 500
        
        # 返回成功结果
        return jsonify({
            'success': True,
            'text': transcribed_text,
            'video_url': video_url,
            'message': '转换成功'
        })
        
    except Exception as e:
        return jsonify({
            'error': f'服务器内部错误: {str(e)}',
            'success': False
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    return jsonify({
        'status': 'healthy',
        'message': '抖音视频转文字API正在运行'
    })

@app.route('/', methods=['GET'])
def home():
    """API文档"""
    return jsonify({
        'name': '抖音视频转文字API',
        'version': '1.0.0',
        'endpoints': {
            'POST /api/convert': {
                'description': '将抖音视频转换为文字',
                'parameters': {
                    'douyin_url': 'string - 抖音视频链接'
                },
                'example': {
                    'douyin_url': 'https://v.douyin.com/...'
                }
            },
            'GET /api/health': {
                'description': '检查API健康状态'
            }
        },
        'usage_example': {
            'curl': 'curl -X POST https://your-api-url.vercel.app/api/convert -H "Content-Type: application/json" -d \'{"douyin_url": "你的抖音链接"}\''
        }
    })

# ... (保持你原有的所有代码不变)

# Vercel Serverless 适配器
def handler(event, context):
    from flask import Response
    
    # 创建 WSGI 环境
    environ = {
        'REQUEST_METHOD': event['httpMethod'],
        'PATH_INFO': event['path'],
        'QUERY_STRING': '',
        'SERVER_NAME': '',
        'SERVER_PORT': '',
        'wsgi.url_scheme': 'https',
        'wsgi.input': event.get('body', ''),
        'wsgi.errors': None,
        'wsgi.version': (1, 0),
        'wsgi.run_once': False,
        'wsgi.multithread': False,
        'wsgi.multiprocess': False
    }
    
    # 处理请求
    def start_response(status, headers):
        pass
        
    response_data = b''.join(app(environ, start_response))
    
    # 返回 Vercel 需要的格式
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json'
        },
        'body': response_data.decode('utf-8')
    }

# 本地开发时直接运行
if __name__ == '__main__':
    app.run(debug=True)