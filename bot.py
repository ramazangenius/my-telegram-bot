import os
import logging
import tempfile
import re
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    Defaults
)
import yt_dlp

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка конфигурации
load_dotenv()
TOKEN = "8019112289:AAFP3XXD4t2LRUU32C3h7LML3V0tP_yts4s"

# Проверка URL YouTube (исправленные экранированные символы)
def is_youtube_url(url: str) -> bool:
    youtube_regex = (
        r'(https?://)?(www\.)?'
        '(youtube|youtu|youtube-nocookie)\.(com|be)/'
        '(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
    )
    return re.match(youtube_regex, url) is not None

# Конфигурации для разных форматов (упрощенные для работы без ffmpeg)
FORMATS = {
    "1080p": {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080][ext=mp4]',
    },
    "720p": {
        'format': 'bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720][ext=mp4]',
    },
    "audio": {
        'format': 'bestaudio/best',
        'extract_audio': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }]
    }
}

BASE_OPTIONS = {
    'outtmpl': '%(title)s.%(ext)s',
    'quiet': True,
    'no_warnings': True,
    'restrictfilenames': True,
    'noplaylist': True,
    'retries': 3,
    'socket_timeout': 30,
    'http_chunk_size': 10485760,
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Как использовать", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎬 YouTube Downloader Bot\n\n"
        "Отправьте мне ссылку на YouTube видео, и я скачаю его для вас.\n"
        "После отправки ссылки вы сможете выбрать формат.",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    text = (
        "📚 Инструкция по использованию:\n\n"
        "1. Отправьте боту ссылку на YouTube видео\n"
        "2. Выберите желаемый формат (1080p, 720p или аудио)\n"
        "3. Дождитесь завершения загрузки\n\n"
        "⚠️ Требования:\n"
        "- Установите FFmpeg для полной функциональности\n"
        "(скачать: https://ffmpeg.org/download.html)"
    )
    
    if query.message:
        await query.edit_message_text(text)
    else:
        await update.message.reply_text(text)

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip()
    
    if not is_youtube_url(url):
        await update.message.reply_text("⚠️ Пожалуйста, отправьте корректную ссылку YouTube")
        return
    
    context.user_data['url'] = url
    
    keyboard = [
        [
            InlineKeyboardButton("1080p", callback_data="format_1080p"),
            InlineKeyboardButton("720p", callback_data="format_720p"),
        ],
        [InlineKeyboardButton("MP3 Аудио", callback_data="format_audio")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🛠 Выберите формат для скачивания:",
        reply_markup=reply_markup
    )

async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get('url')
    if not url:
        await query.edit_message_text("❌ Ошибка: ссылка не найдена")
        return
    
    format_key = query.data.replace("format_", "")
    format_options = FORMATS.get(format_key, FORMATS["720p"])
    
    await query.edit_message_text(f"⏳ Начинаю загрузку в формате {format_key}...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            ydl_opts = {**BASE_OPTIONS, **format_options}
            ydl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')
            
            # Отключаем объединение потоков если ffmpeg не установлен
            if format_key != "audio":
                ydl_opts['format'] = 'best[height<=1080][ext=mp4]' if format_key == "1080p" else 'best[height<=720][ext=mp4]'
                if 'postprocessors' in ydl_opts:
                    del ydl_opts['postprocessors']
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                filesize = os.path.getsize(filename) / (1024 * 1024)  # в MB
                if filesize > 50:
                    await query.edit_message_text(
                        f"❌ Файл слишком большой ({filesize:.1f}MB > 50MB)\n"
                        "Попробуйте выбрать более низкое качество."
                    )
                    return
                
                caption = f"{info.get('title', 'Video')}"
                if format_key != "audio":
                    caption += f" | {info.get('height', '?')}p"
                
                with open(filename, 'rb') as media_file:
                    if format_key == "audio":
                        await context.bot.send_audio(
                            chat_id=query.message.chat_id,
                            audio=media_file,
                            caption=caption,
                            title=info.get('title', 'Audio'),
                            performer=info.get('uploader', 'Unknown'),
                            duration=info.get('duration')
                        )
                    else:
                        await context.bot.send_video(
                            chat_id=query.message.chat_id,
                            video=media_file,
                            caption=caption,
                            duration=info.get('duration'),
                            width=info.get('width'),
                            height=info.get('height'),
                            supports_streaming=True
                        )
                
                await query.delete_message()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="✅ Загрузка завершена успешно!"
                )
                
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download error: {str(e)}")
            error_msg = str(e)
            if "ffmpeg" in error_msg:
                error_msg += "\n\nУстановите FFmpeg для полной функциональности:\nhttps://ffmpeg.org/download.html"
            await query.edit_message_text(f"❌ Ошибка при загрузке: {error_msg}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            await query.edit_message_text(f"❌ Неожиданная ошибка: {str(e)}")

def main():
    app = Application.builder().token(TOKEN).build()
    
    # Обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(help_command, pattern="^help$"))
    
    # Обработчики сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(download_video, pattern="^format_"))
    
    logger.info("Бот запущен и ожидает сообщений...")
    app.run_polling()

if __name__ == "__main__":
    main()
