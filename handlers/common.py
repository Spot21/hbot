import logging
import traceback
import asyncio
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.models import User
from database.db_manager import get_session
from services.stats_service import get_user_stats, generate_leaderboard

logger = logging.getLogger(__name__)


async def check_and_create_user(user_id: int, username: str, full_name: str, role: str) -> bool:
    """Проверка и создание пользователя, если он не существует"""
    try:
        from database.models import User
        from database.db_manager import get_session

        with get_session() as session:
            # Проверяем существование пользователя
            existing_user = session.query(User).filter(User.telegram_id == user_id).first()

            if existing_user:
                # Обновляем существующего пользователя
                existing_user.username = username
                existing_user.full_name = full_name
                existing_user.role = role
                existing_user.last_active = datetime.utcnow()
                if not existing_user.settings:
                    existing_user.settings = '{}'

                logger.info(f"Обновлен пользователь: id={existing_user.id}, роль={role}")
                session.commit()
                return True
            else:
                # Создаем нового пользователя
                new_user = User(
                    telegram_id=user_id,
                    username=username,
                    full_name=full_name,
                    role=role,
                    created_at=datetime.utcnow(),
                    last_active=datetime.utcnow(),
                    settings='{}' if role == 'parent' else None
                )

                session.add(new_user)
                session.commit()

                # Проверяем создание
                check_user = session.query(User).filter(User.telegram_id == user_id).first()
                if check_user:
                    logger.info(f"Создан новый пользователь: id={check_user.id}, роль={role}")
                    return True
                else:
                    logger.error(f"Не удалось создать пользователя с telegram_id={user_id}")
                    return False

    except Exception as e:
        logger.error(f"Ошибка при проверке/создании пользователя: {e}")
        logger.error(traceback.format_exc())
        return False


async def handle_common_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на общие кнопки интерфейса"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    logger.info(f"Обработка нажатия кнопки: {query.data} пользователем {user_id}")

    # Если это выбор роли, обрабатываем особым образом
    if query.data == "common_role_student":
        logger.info(f"Начало регистрации пользователя {user_id} как ученика")
        try:
            telegram_user = update.effective_user
            full_name = f"{telegram_user.first_name} {telegram_user.last_name or ''}"

            # Создаем или обновляем пользователя
            success = await check_and_create_user(
                user_id=user_id,
                username=telegram_user.username,
                full_name=full_name,
                role="student"
            )

            if not success:
                raise Exception("Не удалось создать/обновить пользователя")

            # Отправляем сообщение о успешной регистрации
            await query.edit_message_text(
                "✅ Вы успешно зарегистрированы как ученик!\n\n"
                "Вы можете проходить тесты, отслеживать свою успеваемость и получать достижения."
            )

            # Небольшая пауза перед отображением меню
            await asyncio.sleep(1)

            # Отправляем главное меню
            student_keyboard = [
                [
                    InlineKeyboardButton("📝 Начать тест", callback_data="common_start_test"),
                    InlineKeyboardButton("📊 Моя статистика", callback_data="common_stats")
                ],
                [
                    InlineKeyboardButton("🏆 Достижения", callback_data="common_achievements"),
                    InlineKeyboardButton("🔍 Справка", callback_data="common_help")
                ]
            ]
            student_markup = InlineKeyboardMarkup(student_keyboard)

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Выберите действие:",
                reply_markup=student_markup
            )
            return
        except Exception as e:
            logger.error(f"Ошибка при регистрации ученика: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                "Произошла ошибка при регистрации. Пожалуйста, попробуйте еще раз или обратитесь к администратору."
            )
            return
    elif query.data == "common_role_parent":
        logger.info(f"Начало регистрации пользователя {user_id} как родителя")
        try:
            telegram_user = update.effective_user
            full_name = f"{telegram_user.first_name} {telegram_user.last_name or ''}"

            # Создаем или обновляем пользователя
            success = await check_and_create_user(
                user_id=user_id,
                username=telegram_user.username,
                full_name=full_name,
                role="parent"
            )

            if not success:
                raise Exception("Не удалось создать/обновить пользователя")

            # Отправляем сообщение о успешной регистрации
            await query.edit_message_text(
                "✅ Вы успешно зарегистрированы как родитель!\n\n"
                "Вы можете привязать аккаунт ученика, используя команду /link с кодом, который вам предоставит ученик."
            )

            # Небольшая пауза перед отображением меню
            await asyncio.sleep(1)

            # Отправляем главное меню
            parent_keyboard = [
                [
                    InlineKeyboardButton("🔗 Привязать ученика", callback_data="common_link_student"),
                    InlineKeyboardButton("📊 Отчеты", callback_data="common_reports")
                ],
                [
                    InlineKeyboardButton("⚙️ Настройки", callback_data="common_parent_settings"),
                    InlineKeyboardButton("🔍 Справка", callback_data="common_help")
                ]
            ]
            parent_markup = InlineKeyboardMarkup(parent_keyboard)

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Выберите действие:",
                reply_markup=parent_markup
            )
            return
        except Exception as e:
            logger.error(f"Ошибка при регистрации родителя: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                "Произошла ошибка при регистрации. Пожалуйста, попробуйте еще раз или обратитесь к администратору."
            )
            return

    # Для других кнопок проверяем, зарегистрирован ли пользователь
    try:
        # Получаем роль пользователя
        with get_session() as session:
            user = session.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                logger.warning(f"Пользователь {user_id} не найден в базе при нажатии на кнопку {query.data}")
                await query.edit_message_text(
                    "Кажется, вы еще не зарегистрированы. Пожалуйста, используйте команду /start"
                )
                return

            # Обновляем время последней активности
            user.last_active = datetime.utcnow()
            session.commit()

            role = user.role
            logger.info(f"Роль пользователя {user_id}: {role}")

        # Обработка кнопок выбора роли (для новых пользователей)
        if query.data == "common_link_student":
            await query.edit_message_text(
                "Для привязки аккаунта ученика используйте команду /link с кодом ученика.\n\n"
                "Пример: /link 123456\n\n"
                "Код можно получить у ученика, который должен выполнить команду /mycode"
            )

        elif query.data == "common_reports":
            await query.delete_message()
            context.args = []  # Пустой список аргументов для команды
            # Импортируем функцию здесь, чтобы избежать циклических импортов
            from handlers.parent import get_report
            await get_report(update, context)

        elif query.data == "common_parent_settings":
            await query.delete_message()
            context.args = []  # Пустой список аргументов для команды
            # Импортируем функцию здесь, чтобы избежать циклических импортов
            from handlers.parent import settings
            await settings(update, context)

        elif query.data == "common_admin_panel":
            await query.delete_message()
            # Импортируем функцию здесь, чтобы избежать циклических импортов
            from handlers.admin import admin_panel
            await admin_panel(update, context)

        # Обработка общих кнопок меню
        elif query.data == "common_start_test":
            await query.delete_message()
            # Импортируем функцию здесь, чтобы избежать циклических импортов
            from handlers.student import start_test
            await start_test(update, context)

        elif query.data == "common_stats":
            await query.delete_message()
            # Импортируем функцию здесь, чтобы избежать циклических импортов
            from handlers.student import show_stats
            await show_stats(update, context)

        elif query.data == "common_achievements":
            await query.delete_message()
            # Импортируем функцию здесь, чтобы избежать циклических импортов
            from handlers.student import show_achievements
            await show_achievements(update, context)

        elif query.data == "common_help":
            await query.delete_message()
            # Импортируем функцию здесь, чтобы избежать циклических импортов
            from handlers.start import help_command
            await help_command(update, context)

        elif query.data == "common_leaderboard":
            await show_leaderboard(update, context)

        elif query.data.startswith("common_stats_"):
            # Обработка кнопок выбора периода в статистике
            period = query.data.replace("common_stats_", "")
            await query.delete_message()

            # Создаем аргументы для команды stats
            context.args = [period]
            # Импортируем функцию здесь, чтобы избежать циклических импортов
            from handlers.student import show_stats
            await show_stats(update, context)

    except Exception as e:
        logger.error(f"Error in handle_common_button: {e}")
        logger.error(traceback.format_exc())
        await query.edit_message_text(
            "Произошла ошибка при обработке запроса. Пожалуйста, попробуйте еще раз."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений, которые не являются командами"""
    user_id = update.effective_user.id
    message_text = update.message.text

    # Проверяем, ожидается ли ввод от пользователя для какой-либо операции
    if context.user_data and "admin_state" in context.user_data:
        # Перенаправляем ввод администратора
        from handlers.admin import handle_admin_input
        await handle_admin_input(update, context)
        return
    elif context.user_data and "student_state" in context.user_data:
        # Здесь можно добавить обработку состояний ученика, если понадобится
        pass
    elif context.user_data and "parent_state" in context.user_data:
        # Здесь можно добавить обработку состояний родителя, если понадобится
        pass

    # В противном случае отправляем стандартный ответ с подсказкой
    await update.message.reply_text(
        "Я не понимаю ваше сообщение. Пожалуйста, используйте команды или кнопки для взаимодействия."
        "\n\nДля получения справки введите /help"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок для логирования и информирования пользователя"""
    logger.error(f"Exception while handling an update: {context.error}")

    # Логируем трассировку ошибки
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    logger.error(f"Exception traceback: {tb_string}")

    # Отправляем сообщение пользователю
    if update and hasattr(update, "effective_chat"):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте еще раз или обратитесь к администратору."
        )


async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать таблицу лидеров"""
    query = update.callback_query

    # Получаем период, если указан
    period = context.args[0] if context.args else "week"
    if period not in ["week", "month", "year", "all"]:
        period = "week"

    # Получаем таблицу лидеров
    leaderboard_result = generate_leaderboard(period, limit=10)

    if not leaderboard_result["success"]:
        if query:
            await query.edit_message_text(
                f"Ошибка получения таблицы лидеров: {leaderboard_result['message']}"
            )
        else:
            await update.message.reply_text(
                f"Ошибка получения таблицы лидеров: {leaderboard_result['message']}"
            )
        return

    if not leaderboard_result["has_data"]:
        # Кнопки для выбора периода
        keyboard = [
            [
                InlineKeyboardButton("За неделю", callback_data="common_leaderboard_week"),
                InlineKeyboardButton("За месяц", callback_data="common_leaderboard_month")
            ],
            [
                InlineKeyboardButton("За год", callback_data="common_leaderboard_year"),
                InlineKeyboardButton("За всё время", callback_data="common_leaderboard_all")
            ],
            [
                InlineKeyboardButton("🔙 Назад", callback_data="common_stats")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.edit_message_text(
                f"За выбранный период ({get_period_name(period)}) нет данных для составления таблицы лидеров.",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"За выбранный период ({get_period_name(period)}) нет данных для составления таблицы лидеров.",
                reply_markup=reply_markup
            )
        return

    # Формируем сообщение с таблицей лидеров
    message = f"🏆 *Таблица лидеров за {get_period_name(period)}*\n\n"

    for i, user_data in enumerate(leaderboard_result["leaderboard"], 1):
        name = user_data["full_name"] or user_data["username"] or f"Ученик {user_data['id']}"
        score = user_data["score"]
        tests = user_data["tests_count"]

        message += f"{i}. {name} - {score} баллов ({tests} тестов)\n"

    # Кнопки для выбора периода
    keyboard = [
        [
            InlineKeyboardButton("За неделю", callback_data="common_leaderboard_week"),
            InlineKeyboardButton("За месяц", callback_data="common_leaderboard_month")
        ],
        [
            InlineKeyboardButton("За год", callback_data="common_leaderboard_year"),
            InlineKeyboardButton("За всё время", callback_data="common_leaderboard_all")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="common_stats")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )


def get_period_name(period: str) -> str:
    """Получение названия периода на русском языке"""
    if period == "week":
        return "неделю"
    elif period == "month":
        return "месяц"
    elif period == "year":
        return "год"
    elif period == "all":
        return "всё время"
    else:
        return "неизвестный период"