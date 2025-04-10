from database.models import User
from datetime import datetime
import logging
import asyncio
import signal
import traceback
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram import Update
from config import BOT_TOKEN, ADMINS, DB_ENGINE

from handlers import start, student, parent, admin, common
from database.db_manager import init_db, get_session, engine
from services.notification import NotificationService

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные для управления состоянием бота
application = None
notification_service = None
running = False


async def shutdown(signal_name=None):
    """Корректное завершение работы бота"""
    global running, application, notification_service

    if not running:
        return

    logger.info(f"Shutting down bot{f' (signal: {signal_name})' if signal_name else ''}")
    running = False

    try:
        if notification_service:
            await notification_service.stop()

        if application and application.updater.running:
            await application.updater.stop()

        if application:
            await application.stop()
            await application.shutdown()

        logger.info("Bot shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
        logger.error(traceback.format_exc())


async def test_db():
    """Тестирование работы с базой данных"""
    try:
        logger.info("Тестирование создания пользователя")
        with get_session() as session:
            # Создаем тестового пользователя
            test_user = User(
                telegram_id=9999999,  # Тестовый ID
                username="test_user",
                full_name="Test User",
                role="parent",
                created_at=datetime.utcnow(),
                last_active=datetime.utcnow(),
                settings='{}'
            )
            session.add(test_user)
            session.commit()

            # Проверяем, что пользователь действительно создан
            created_user = session.query(User).filter(User.telegram_id == 9999999).first()
            if created_user:
                logger.info(f"Тестовый пользователь успешно создан: {created_user.id}, {created_user.role}")
            else:
                logger.error("Ошибка! Тестовый пользователь не найден после создания")

    except Exception as e:
        logger.error(f"Ошибка при тестировании базы данных: {e}")
        logger.error(traceback.format_exc())


async def test_db_detailed():
    """Детальное тестирование работы с базой данных"""
    try:
        from database.models import User
        from sqlalchemy import inspect

        logger.info("--- Начало детального тестирования базы данных ---")

        # Проверка подключения к базе данных
        logger.info(f"Используется движок базы данных: {DB_ENGINE}")
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logger.info(f"Таблицы в базе данных: {tables}")

        # Проверка транзакций
        with get_session() as session:
            # Создаем временного пользователя
            test_user = User(
                telegram_id=7777777,
                username="test_transaction",
                full_name="Test Transaction",
                role="student"
            )
            session.add(test_user)
            logger.info("Пользователь добавлен в сессию")

            # Проверка добавления пользователя до commit
            session.flush()
            temp_id = test_user.id
            logger.info(f"ID пользователя после flush: {temp_id}")

            # Отмена транзакции
            session.rollback()
            logger.info("Транзакция отменена")

            # Проверка после отмены
            check_user = session.query(User).filter(User.telegram_id == 7777777).first()
            logger.info(f"Пользователь после rollback: {check_user}")

        # Новая транзакция для создания пользователя
        with get_session() as session:
            logger.info("Создание тестового пользователя в новой транзакции")
            test_user = User(
                telegram_id=6666666,
                username="test_creation",
                full_name="Test Creation",
                role="parent",
                settings='{}'
            )
            session.add(test_user)
            logger.info("Пользователь добавлен, коммит...")
            session.commit()
            logger.info("Транзакция зафиксирована")

            # Проверка в той же сессии
            created_user = session.query(User).filter(User.telegram_id == 6666666).first()
            if created_user:
                logger.info(f"Пользователь создан успешно: id={created_user.id}, роль={created_user.role}")
            else:
                logger.error("Пользователь не найден в той же сессии!")

        # Проверка в новой сессии
        with get_session() as session:
            logger.info("Проверка в новой сессии")
            verification_user = session.query(User).filter(User.telegram_id == 6666666).first()
            if verification_user:
                logger.info(
                    f"Пользователь найден в новой сессии: id={verification_user.id}, роль={verification_user.role}")
            else:
                logger.error("Пользователь не найден в новой сессии!")

        logger.info("--- Завершение детального тестирования базы данных ---")

    except Exception as e:
        logger.error(f"Ошибка при детальном тестировании базы данных: {e}")
        logger.error(traceback.format_exc())



async def main():
    """Запуск бота"""
    global running, application, notification_service
    await test_db()
    await test_db_detailed()
    try:
        # Инициализация базы данных
        init_db()

        # Создание экземпляра приложения с настройками таймаутов
        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .read_timeout(30)
            .write_timeout(30)
            .connect_timeout(30)
            .pool_timeout(30)
            .build()
        )

        # Регистрация обработчиков команд
        application.add_handler(CommandHandler("start", start.start_command))
        application.add_handler(CommandHandler("help", start.help_command))

        # Обработчики для ученика
        application.add_handler(CommandHandler("test", student.start_test))
        application.add_handler(CommandHandler("stats", student.show_stats))
        application.add_handler(CommandHandler("achievements", student.show_achievements))
        application.add_handler(CommandHandler("mycode", start.mycode_command))

        # Обработчики для родителя
        application.add_handler(CommandHandler("link", parent.link_student))
        application.add_handler(CommandHandler("report", parent.get_report))
        application.add_handler(CommandHandler("settings", parent.settings))

        # Обработчики для администратора
        application.add_handler(CommandHandler("admin", admin.admin_panel))
        application.add_handler(CommandHandler("add_question", admin.add_question))
        application.add_handler(CommandHandler("import", admin.import_questions))

        # Обработка кнопок и inline-клавиатур
        application.add_handler(CallbackQueryHandler(student.handle_test_button, pattern=r'^quiz_'))
        application.add_handler(CallbackQueryHandler(parent.handle_parent_button, pattern=r'^parent_'))
        application.add_handler(CallbackQueryHandler(admin.handle_admin_button, pattern=r'^admin_'))
        application.add_handler(CallbackQueryHandler(common.handle_common_button, pattern=r'^common_'))

        # Обработка обычных текстовых сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, common.handle_message))

        # Обработка загруженных файлов
        application.add_handler(MessageHandler(filters.Document.ALL, admin.handle_document))

        # Обработка ошибок
        application.add_error_handler(common.error_handler)

        # Инициализация сервиса уведомлений
        notification_service = NotificationService(application)
        await notification_service.start()

        # Установка обработчиков сигналов для корректного завершения
        import platform
        if platform.system() != 'Windows':  # Только для Unix-подобных систем
            import signal
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop = asyncio.get_running_loop()
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(shutdown(s.name))
                )

        # Запуск бота
        running = True
        await application.initialize()
        await application.start()
        logger.info("Bot started")

        # Запускаем polling и ждем завершения
        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

        # Бесконечный цикл, чтобы бот работал до получения сигнала завершения
        while running:
            await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"Error during bot execution: {e}")
        logger.error(traceback.format_exc())
    finally:
        await shutdown()


if __name__ == '__main__':

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        logger.error(traceback.format_exc())