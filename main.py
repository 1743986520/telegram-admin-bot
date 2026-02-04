#!/usr/bin/env python3
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# 設定
BOT_TOKEN = 8222440671:AAEgZQqZRnHMJu6Lw9IsO2VXo_t2-n_QK9Q

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """有人進群發歡迎訊息"""
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            continue
        
        username = f"@{member.username}" if member.username else member.full_name
        welcome_msg = f"歡迎 {username} 進群，置頂內容看一看"
        
        await update.message.reply_text(welcome_msg, parse_mode=ParseMode.MARKDOWN)

def main():
    """啟動機器人"""
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.run_polling()

if __name__ == '__main__':
    main()