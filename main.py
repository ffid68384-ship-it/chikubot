def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("c", cmd_c))
    app.add_handler(CommandHandler("settradeid", cmd_settradeid))
    app.add_handler(CommandHandler("minus", cmd_minus))
    app.add_handler(CommandHandler("unhold", cmd_unhold))
    app.add_handler(CommandHandler("earnings", cmd_earnings))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("coowneradd", cmd_coowneradd))
    app.add_handler(CommandHandler("coownerremove", cmd_coownerremove))
    app.add_handler(CommandHandler("coowners", cmd_coowners))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("fee", cmd_fee))
    app.add_handler(CommandHandler("fees", cmd_fee))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app.add_handler(CommandHandler("admins", cmd_admins))
    app.add_handler(CommandHandler("chatid", cmd_chatid))
    
    app.add_handler(CommandHandler("form", cmd_form))
    app.add_handler(CommandHandler("deal", cmd_deal))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("hold", cmd_hold))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("refund", cmd_refund))
    app.add_handler(CommandHandler("stats", cmd_stats))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    
    port = int(os.environ.get("PORT", 10000))
    import threading
    threading.Thread(target=lambda: web_app.run(host='0.0.0.0', port=port), daemon=True).start()
    
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
    
