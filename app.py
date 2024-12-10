# 导入所需的Flask模块和其他库
from flask import Flask, render_template, request, jsonify
import hashlib  # 用于生成MD5签名
import random   # 用于生成随机数
import requests # 用于发送HTTP请求
import base64
import os
from werkzeug.utils import secure_filename
import time
from PIL import Image
from models import db, TranslationLog, SystemLog
import logging
from logging.handlers import RotatingFileHandler
import traceback
import json  # 添加这行

# 创建Flask应用实例
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///translations.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 初始化数据库
db.init_app(app)

# 确保数据库表存在
with app.app_context():
    db.create_all()

# 创建日志目录
if not os.path.exists('logs'):
    os.makedirs('logs')

# 配置文件日志
file_handler = RotatingFileHandler('logs/app.log', maxBytes=1024*1024, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)

app.logger.setLevel(logging.INFO)
app.logger.info('机器翻译系统启动')

def log_system(level, module, message, details=None):
    """记录系统日志"""
    # 如果 details 是字典，将其转换为 JSON 字符串
    if isinstance(details, dict):
        details = json.dumps(details, ensure_ascii=False)
        
    log = SystemLog(
        level=level,
        module=module,
        message=message,
        details=details,
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string
    )
    db.session.add(log)
    
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"日志记录失败: {str(e)}")

# 定义翻译器类
class Translator:
    def __init__(self):
        # 百度翻译API配置
        self.appid = "20241204002219238"  # API ID
        self.secret_key = "KX2lAFGlIAyzdVhrKP_B"  # 密钥
        
        # 扩展支持的语言列表
        self.languages = {
            '自动检测': 'auto',
            '中文': 'zh',
            '英语': 'en',
            '日语': 'jp',
            '韩语': 'kor',
            '法语': 'fra',
            '德语': 'de',
            '俄语': 'ru',
            '西班牙语': 'spa',
            '意大利语': 'it',
            '葡萄牙语': 'pt',
            '越南语': 'vie',
            '泰语': 'th',
            '阿拉伯语': 'ara',
        }

    def detect_language(self, text):
        """使用百度翻译语种识别API"""
        url = "https://fanyi-api.baidu.com/api/trans/vip/language"
        
        salt = str(random.randint(32768, 65536))
        sign = self.appid + text + salt + self.secret_key
        sign = hashlib.md5(sign.encode()).hexdigest()
        
        params = {
            'q': text,
            'appid': self.appid,
            'salt': salt,
            'sign': sign
        }
        
        try:
            response = requests.post(url, data=params)
            result = response.json()
            
            # 修改这里：error_code 为 0 表示成功
            if 'error_code' in result and str(result['error_code']) != '0':
                print(f"语种识别返回错误: {result}")
                return 'auto'
            else:
                 return result.get('data', {}).get('src', 'auto')
            
        except Exception as e:
            print(f"语种识别错误: {str(e)}")
            return 'auto'

    def translate(self, text, to_lang, from_lang='auto'):
        """调用百度翻译API进行翻译"""
        url = "https://fanyi-api.baidu.com/api/trans/vip/translate"
        
        # 处理多行文本，保持原有的换行格式
        lines = text.split('\n')
        translated_lines = []
        
        # 如果自动检测，先调用语种识别API
        if from_lang == 'auto':
            from_lang = self.detect_language(text)
        
        for line in lines:
            if not line.strip():  # 如果是空行，直接添加空行
                translated_lines.append('')
                continue
            
            salt = random.randint(32768, 65536)
            sign = self.appid + line + str(salt) + self.secret_key
            sign = hashlib.md5(sign.encode()).hexdigest()
            
            params = {
                'appid': self.appid,
                'q': line,
                'from': from_lang,
                'to': to_lang,
                'salt': salt,
                'sign': sign
            }
            
            try:
                response = requests.get(url, params=params)
                result = response.json()
                
                if 'error_code' in result:
                    raise Exception(f"翻译错误 (错误码: {result['error_code']})")
                
                translated_lines.append(result['trans_result'][0]['dst'])
                
            except Exception as e:
                print(f"翻译错误: {str(e)}")
                translated_lines.append(line)  # 如果翻译失败，保留原文
        
        # 合并所有翻译结果，保持原有的换行格式
        translated_text = '\n'.join(translated_lines)
        quality_score = self.calculate_quality_score(text, translated_text)
        
        return {
            'translated_text': translated_text,
            'quality_score': quality_score,
            'detected_lang': from_lang if from_lang != 'auto' else None
        }
    
    def calculate_quality_score(self, source_text, translated_text):
        """计算翻译质量评分"""
        score = 0
        
        # 长度比例评分 (30分)
        source_len = len(source_text)
        trans_len = len(translated_text)
        length_ratio = trans_len / source_len if source_len > 0 else 0
        
        if 0.6 <= length_ratio <= 1.4:
            length_score = 30
        else:
            length_score = 30 * (1 - min(abs(length_ratio - 1), 1))
        score += length_score
        
        # 标点符号使用评分 (20分)
        source_puncts = sum(1 for c in source_text if c in ',.!?;，。！？；')
        trans_puncts = sum(1 for c in translated_text if c in ',.!?;，。！？；')
        
        if source_puncts > 0:
            punct_ratio = trans_puncts / source_puncts
            punct_score = 20 * (1 - min(abs(punct_ratio - 1), 1))
        else:
            punct_score = 20 if trans_puncts == 0 else 15
        score += punct_score
        
        # 文本完整性评分 (30分)
        if translated_text.endswith(('。', '.', '！', '?', '？', '!', '；', ';')):
            score += 30
        else:
            score += 15
        
        # 基础合理性评分 (20分)
        words_count = len(translated_text.split())
        if words_count >= 2:
            score += 20
        else:
            score += 10 * words_count
        
        return int(score)
    
    def translate_image(self, image_file, to_lang='en'):
        """使用百度图片翻译API"""
        url = "https://fanyi-api.baidu.com/api/trans/sdk/picture"
        
        # 读取原始图片数据
        image_content = image_file.read()
        
        # 检查图片大小
        if len(image_content) > 4 * 1024 * 1024:  # 4M
            raise Exception("图片大小不能超过4M")
        
        # 计算图片的md5值（使用原始图片数据）
        image_md5 = hashlib.md5(image_content).hexdigest().lower()
        
        # 生成随机数和其他参数
        salt = str(random.randint(32768, 65536))
        cuid = "APICUID"
        mac = "mac"
        
        # 生成签�
        sign_str = self.appid + image_md5 + salt + cuid + mac + self.secret_key
        sign = hashlib.md5(sign_str.encode()).hexdigest().lower()
        
        # 构建multipart/form-data请求数据
        data = {
            'from': 'auto',
            'to': to_lang,
            'appid': self.appid,
            'salt': salt,
            'sign': sign,
            'cuid': cuid,
            'mac': mac,
            'version': '3'
        }
        
        files = {
            'image': ('image.jpg', image_content, 'image/jpeg')
        }
        
        try:
            response = requests.post(url, data=data, files=files)
            result = response.json()
            
            if 'error_code' in result and str(result['error_code']) != '0':
                print(f"翻译返回错误: {result}")
                raise Exception(f"翻译错误 (错误码: {result['error_code']})")
            
            return result
            
        except Exception as e:
            print(f"图片翻译错误: {str(e)}")
            return None

# 创建翻译器实例
translator = Translator()

# 定义根路由
@app.route('/')
def index():
    # 渲染主页模板，传入支持的语言列表
    return render_template('index.html', languages=translator.languages)

# 定义翻译API路由
@app.route('/translate', methods=['POST'])
def translate():
    try:
        data = request.get_json()
        text = data.get('text', '')
        to_lang = data.get('to_lang', '')
        from_lang = data.get('from_lang', 'auto')
        
        # 记录开始翻译的日志
        log_details = {
            'text': text[:100] + '...' if len(text) > 100 else text,
            'from': from_lang,
            'to': to_lang
        }
        log_system('INFO', 'translate', '开始翻译', log_details)
        
        if not text or not to_lang:
            error = '请提供完整翻译信息'
            log_system('WARNING', 'translate', error)
            return jsonify({'error': error}), 400
            
        result = translator.translate(text, to_lang, from_lang)
        
        # 记录翻译日志
        log = TranslationLog(
            type='text',
            source_text=text,
            translated_text=result['translated_text'],
            from_lang=from_lang if from_lang != 'auto' else result.get('detected_lang', 'auto'),
            to_lang=to_lang,
            quality_score=result['quality_score'],
            ip_address=request.remote_addr
        )
        db.session.add(log)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"翻译日志记录失败: {str(e)}")
        
        return jsonify(result)
        
    except Exception as e:
        error_details = traceback.format_exc()
        log_system('ERROR', 'translate', str(e), error_details)
        return jsonify({'error': str(e)}), 500

# 修改图片上传路由，添加图片验证
@app.route('/translate_image', methods=['POST'])
def translate_image():
    try:
        if 'image' not in request.files:
            error = '没有上传图片'
            log_system('WARNING', 'translate_image', error)
            return jsonify({'error': error}), 400
            
        image_file = request.files['image']
        if image_file.filename == '':
            error = '没有选择图片'
            log_system('WARNING', 'translate_image', error)
            return jsonify({'error': error}), 400
            
        # 获取目标语言参数
        to_lang = request.form.get('to_lang', 'en')
        
        # 记录开始翻译的日志
        log_details = {
            'filename': image_file.filename,
            'to_lang': to_lang,
            'file_size': len(image_file.read())  # 记录文件大小
        }
        image_file.seek(0)  # 重置文件指针
        log_system('INFO', 'translate_image', '开始图片翻译', log_details)
        
        # 检查文件类型
        allowed_extensions = {'png', 'jpg', 'jpeg'}
        file_ext = image_file.filename.rsplit('.', 1)[1].lower()
        if not '.' in image_file.filename or file_ext not in allowed_extensions:
            error = '仅支持jpg、jpeg、png格式图片'
            log_system('WARNING', 'translate_image', error, log_details)
            return jsonify({'error': error}), 400
            
        # 读取图片以检查尺寸
        img = Image.open(image_file)
        width, height = img.size
        
        # 检查图片尺寸
        if width < 30 or height < 30:
            error = '图片最短边至少需要30像素'
            log_system('WARNING', 'translate_image', error, log_details)
            return jsonify({'error': error}), 400
        if width > 4096 or height > 4096:
            error = '图片最长边不能超过4096像素'
            log_system('WARNING', 'translate_image', error, log_details)
            return jsonify({'error': error}), 400
        if max(width/height, height/width) > 3:
            error = '图片长宽比需要在3:1以内'
            log_system('WARNING', 'translate_image', error, log_details)
            return jsonify({'error': error}), 400
            
        # 重置文件指针
        image_file.seek(0)
        
        result = translator.translate_image(image_file, to_lang)
        if result is None:
            error = '图片翻译失败'
            log_system('ERROR', 'translate_image', error, log_details)
            return jsonify({'error': error}), 500
            
        # 记录成功的翻译日志
        log = TranslationLog(
            type='image',
            source_text=f"图片: {image_file.filename} ({width}x{height})",
            translated_text=str([item['dst'] for item in result['data']['content']]),
            from_lang='auto',
            to_lang=to_lang,
            ip_address=request.remote_addr
        )
        db.session.add(log)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"图片翻译日志记录失败: {str(e)}")
            
        # 记录成功的系统日志
        log_system('INFO', 'translate_image', '图片翻译成功', {
            **log_details,
            'width': width,
            'height': height,
            'text_count': len(result['data']['content'])
        })
            
        return jsonify(result)
        
    except Exception as e:
        error_details = traceback.format_exc()
        log_system('ERROR', 'translate_image', str(e), error_details)
        return jsonify({'error': str(e)}), 500

# 添加日志查看路由
@app.route('/logs')
def view_logs():
    return render_template('logs.html')

# 添加获取日志的API
@app.route('/api/logs')
def get_logs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    logs = TranslationLog.query.order_by(TranslationLog.timestamp.desc())
    pagination = logs.paginate(page=page, per_page=per_page)
    
    return jsonify({
        'logs': [{
            'id': log.id,
            'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'type': log.type,
            'source_text': log.source_text,
            'translated_text': log.translated_text,
            'from_lang': log.from_lang,
            'to_lang': log.to_lang,
            'quality_score': log.quality_score,
            'error': log.error,
            'ip_address': log.ip_address
        } for log in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

# 添加系统日志查看路由
@app.route('/system-logs')
def view_system_logs():
    return render_template('system_logs.html')

# 添加获取系统日志的API
@app.route('/api/system-logs')
def get_system_logs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    level = request.args.get('level')  # 可选的日志级别过滤
    
    query = SystemLog.query.order_by(SystemLog.timestamp.desc())
    if level:
        query = query.filter_by(level=level)
        
    pagination = query.paginate(page=page, per_page=per_page)
    
    return jsonify({
        'logs': [{
            'id': log.id,
            'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'level': log.level,
            'module': log.module,
            'message': log.message,
            'details': log.details,
            'ip_address': log.ip_address,
            'user_agent': log.user_agent
        } for log in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

# 程序入口
if __name__ == '__main__':
    # 以调试模式运行Flask应用
    app.run(debug=True)