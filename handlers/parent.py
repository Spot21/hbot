import logging
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from services.parent_service import ParentService
from database.models import User
from database.db_manager import get_session

logger = logging.getLogger(__name__)
parent_service = ParentService()


async def check_parent_role(update: Update) -> bool:
    """Проверка, является ли пользователь родителем"""
    user_id = update.effective_user.id

    with get_session() as session:
        user = session.query(User).filter(User.telegram_id == user_id).first()
        if not user or user.role != "parent":
            await update.message.reply_text(
                "Эта команда доступна только для родителей. "
                "Пожалуйста, обратитесь к администратору для изменения роли."
            )
            return False
    return True


async def link_student(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /link для привязки аккаунта ученика к родителю"""
    user_id = update.effective_user.id

    # Проверяем, является ли пользователь родителем
    try:
        with get_session() as session:
            user = session.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                await update.message.reply_text(
                    "Кажется, вы еще не зарегистрированы. Пожалуйста, используйте команду /start"
                )
                return

            if user.role != "parent":
                await update.message.reply_text(
                    "Эта команда доступна только для родителей. "
                    "Пожалуйста, обратитесь к администратору для изменения роли."
                )
                return
    except Exception as e:
        logger.error(f"Error checking parent role: {e}")
        await update.message.reply_text(
            "Произошла ошибка при проверке ваших данных. Пожалуйста, попробуйте позже."
        )
        return

    # Проверяем, есть ли у команды аргумент с кодом ученика
    if not context.args:
        await update.message.reply_text(
            "Для привязки аккаунта ученика используйте команду /link с кодом ученика.\n\n"
            "Пример: /link 123456\n\n"
            "Код можно получить у ученика, который должен выполнить команду /mycode"
        )
        return

    student_code = context.args[0]

    # Привязываем ученика
    result = parent_service.link_student(user_id, student_code)

    if result["success"]:
        await update.message.reply_text(
            f"{result['message']}\n\n"
            "Теперь вы можете получать отчеты о его успеваемости."
        )
    else:
        await update.message.reply_text(
            f"Ошибка привязки: {result['message']}\n\n"
            "Пожалуйста, проверьте код и попробуйте еще раз."
        )


async def get_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /report для получения отчета об успеваемости ученика"""
    if not await check_parent_role(update):
        return

    user_id = update.effective_user.id

    # Получаем список привязанных учеников
    students_result = parent_service.get_linked_students(user_id)

    if not students_result["success"]:
        await update.message.reply_text(
            f"Ошибка: {students_result['message']}"
        )
        return

    students = students_result["students"]

    if not students:
        await update.message.reply_text(
            "У вас нет привязанных учеников. Используйте команду /link с кодом ученика для привязки."
        )
        return

    # Если указан идентификатор ученика и период, сразу показываем отчет
    if len(context.args) >= 2:
        try:
            student_id = int(context.args[0])
            period = context.args[1]
            if period not in ["week", "month", "year"]:
                period = "week"

            # Проверяем, есть ли такой ученик среди привязанных
            student_found = False
            for student in students:
                if student["id"] == student_id:
                    student_found = True
                    break

            if not student_found:
                await update.message.reply_text(
                    "Указанный ученик не найден среди привязанных к вашему аккаунту."
                )
                return

            # Показываем отчет
            await show_student_report(update, context, student_id, period)
            return

        except (ValueError, IndexError):
            # Если аргументы неверны, показываем меню выбора ученика
            pass

    # Показываем меню выбора ученика
    keyboard = []
    for student in students:
        name = student["full_name"] or student["username"] or f"Ученик {student['id']}"
        keyboard.append([
            InlineKeyboardButton(
                name,
                callback_data=f"parent_student_{student['id']}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Выберите ученика для просмотра отчета:",
        reply_markup=reply_markup
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /settings для настройки уведомлений и прочих параметров"""
    if not await check_parent_role(update):
        return

    user_id = update.effective_user.id

    # Получаем текущие настройки
    settings_result = parent_service.get_parent_settings(user_id)

    if not settings_result["success"]:
        await update.message.reply_text(
            f"Ошибка получения настроек: {settings_result['message']}"
        )
        return

    # Получаем список привязанных учеников
    students_result = parent_service.get_linked_students(user_id)

    if not students_result["success"]:
        await update.message.reply_text(
            f"Ошибка: {students_result['message']}"
        )
        return

    students = students_result["students"]

    if not students:
        await update.message.reply_text(
            "У вас нет привязанных учеников. Используйте команду /link с кодом ученика для привязки."
        )
        return

    # Если указан идентификатор ученика, показываем настройки для него
    if context.args:
        try:
            student_id = int(context.args[0])

            # Проверяем, есть ли такой ученик среди привязанных
            student_found = False
            student_name = ""
            for student in students:
                if student["id"] == student_id:
                    student_found = True
                    student_name = student["full_name"] or student["username"] or f"Ученик {student['id']}"
                    break

            if not student_found:
                await update.message.reply_text(
                    "Указанный ученик не найден среди привязанных к вашему аккаунту."
                )
                return

            # Показываем настройки для ученика
            await show_student_settings(update, context, student_id, student_name)
            return

        except (ValueError, IndexError):
            # Если аргументы неверны, показываем меню выбора ученика
            pass

    # Показываем меню выбора ученика
    keyboard = []
    for student in students:
        name = student["full_name"] or student["username"] or f"Ученик {student['id']}"
        keyboard.append([
            InlineKeyboardButton(
                name,
                callback_data=f"parent_settings_{student['id']}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Выберите ученика для настройки уведомлений:",
        reply_markup=reply_markup
    )


async def handle_parent_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий кнопок в разделе родителя"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Проверяем роль пользователя
    with get_session() as session:
        user = session.query(User).filter(User.telegram_id == user_id).first()
        if not user or user.role != "parent":
            await query.edit_message_text(
                "Эта функция доступна только для родителей. "
                "Пожалуйста, обратитесь к администратору для изменения роли."
            )
            return

    try:
        if query.data.startswith("parent_student_"):
            # Выбор ученика для отчета
            student_id = int(query.data.replace("parent_student_", ""))

            # Показываем меню выбора периода
            keyboard = [
                [
                    InlineKeyboardButton("За неделю", callback_data=f"parent_report_{student_id}_week"),
                    InlineKeyboardButton("За месяц", callback_data=f"parent_report_{student_id}_month")
                ],
                [
                    InlineKeyboardButton("За год", callback_data=f"parent_report_{student_id}_year"),
                    InlineKeyboardButton("Назад к списку учеников", callback_data="parent_back_students")
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "Выберите период для отчета:",
                reply_markup=reply_markup
            )

        elif query.data.startswith("parent_report_"):
            # Показ отчета об успеваемости
            parts = query.data.split("_")
            student_id = int(parts[2])
            period = parts[3]

            # Генерируем и показываем отчет
            await show_student_report(update, context, student_id, period)

        elif query.data.startswith("parent_settings_"):
            # Настройки для ученика
            student_id = int(query.data.replace("parent_settings_", ""))

            # Получаем информацию об ученике
            students_result = parent_service.get_linked_students(user_id)
            if not students_result["success"]:
                await query.edit_message_text(f"Ошибка: {students_result['message']}")
                return

            students = students_result["students"]
            student_name = ""
            for student in students:
                if student["id"] == student_id:
                    student_name = student["full_name"] or student["username"] or f"Ученик {student['id']}"
                    break

            # Показываем настройки для ученика
            await show_student_settings(update, context, student_id, student_name, query=query)

        elif query.data.startswith("parent_toggle_"):
            # Переключение настроек уведомлений
            parts = query.data.split("_")
            setting_type = parts[2]
            student_id = int(parts[3])

            # Получаем текущие настройки
            settings_result = parent_service.get_parent_settings(user_id)

            if not settings_result["success"]:
                await query.edit_message_text(f"Ошибка получения настроек: {settings_result['message']}")
                return

            settings = settings_result["settings"]

            # Убеждаемся, что структура настроек существует
            if "student_notifications" not in settings:
                settings["student_notifications"] = {}

            if str(student_id) not in settings["student_notifications"]:
                settings["student_notifications"][str(student_id)] = {}

            student_settings = settings["student_notifications"][str(student_id)]

            # Переключаем настройку
            current_value = student_settings.get(setting_type, False)
            student_settings[setting_type] = not current_value

            # Сохраняем настройки
            result = parent_service.setup_notifications(user_id, student_id, student_settings)

            if not result["success"]:
                await query.edit_message_text(f"Ошибка сохранения настроек: {result['message']}")
                return

            # Получаем имя ученика
            students_result = parent_service.get_linked_students(user_id)
            student_name = ""
            if students_result["success"]:
                for student in students_result["students"]:
                    if student["id"] == student_id:
                        student_name = student["full_name"] or student["username"] or f"Ученик {student['id']}"
                        break

            # Показываем обновленные настройки
            await show_student_settings(update, context, student_id, student_name, query=query)

        elif query.data.startswith("parent_threshold_"):
            # Изменение порогового значения
            parts = query.data.split("_")
            threshold_type = parts[2]
            student_id = int(parts[3])
            action = parts[4]  # up или down

            # Получаем текущие настройки
            settings_result = parent_service.get_parent_settings(user_id)

            if not settings_result["success"]:
                await query.edit_message_text(f"Ошибка получения настроек: {settings_result['message']}")
                return

            settings = settings_result["settings"]

            # Убеждаемся, что структура настроек существует
            if "student_notifications" not in settings:
                settings["student_notifications"] = {}

            if str(student_id) not in settings["student_notifications"]:
                settings["student_notifications"][str(student_id)] = {}

            student_settings = settings["student_notifications"][str(student_id)]

            # Устанавливаем значения по умолчанию
            if threshold_type == "low_score_threshold" and threshold_type not in student_settings:
                student_settings[threshold_type] = 60
            elif threshold_type == "high_score_threshold" and threshold_type not in student_settings:
                student_settings[threshold_type] = 90

            # Изменяем пороговое значение
            current_value = student_settings.get(threshold_type,
                                                 60 if threshold_type == "low_score_threshold" else 90)

            if action == "up":
                new_value = min(current_value + 5, 100)
            else:  # down
                new_value = max(current_value - 5, 0)

            student_settings[threshold_type] = new_value

            # Сохраняем настройки
            result = parent_service.setup_notifications(user_id, student_id, student_settings)

            if not result["success"]:
                await query.edit_message_text(f"Ошибка сохранения настроек: {result['message']}")
                return

            # Получаем имя ученика
            students_result = parent_service.get_linked_students(user_id)
            student_name = ""
            if students_result["success"]:
                for student in students_result["students"]:
                    if student["id"] == student_id:
                        student_name = student["full_name"] or student["username"] or f"Ученик {student['id']}"
                        break

            # Показываем обновленные настройки
            await show_student_settings(update, context, student_id, student_name, query=query)

        elif query.data == "parent_back_students":
            # Возврат к списку учеников
            students_result = parent_service.get_linked_students(user_id)

            if not students_result["success"]:
                await query.edit_message_text(f"Ошибка: {students_result['message']}")
                return

            students = students_result["students"]

            # Показываем меню выбора ученика
            keyboard = []
            for student in students:
                name = student["full_name"] or student["username"] or f"Ученик {student['id']}"
                keyboard.append([
                    InlineKeyboardButton(
                        name,
                        callback_data=f"parent_student_{student['id']}"
                    )
                ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "Выберите ученика для просмотра отчета:",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Error in handle_parent_button: {e}")
        await query.edit_message_text(
            "Произошла ошибка при обработке запроса. Пожалуйста, попробуйте еще раз."
        )


async def show_student_report(update: Update, context: ContextTypes.DEFAULT_TYPE, student_id: int, period: str) -> None:
    """Показ отчета об успеваемости ученика"""
    user_id = update.effective_user.id
    query = update.callback_query

    # Генерируем отчет
    report_result = parent_service.generate_student_report(user_id, student_id, period)

    if not report_result["success"]:
        if query:
            await query.edit_message_text(f"Ошибка: {report_result['message']}")
        else:
            await update.message.reply_text(f"Ошибка: {report_result['message']}")
        return

    if not report_result["has_data"]:
        # Кнопки для выбора другого периода и возврата
        keyboard = [
            [
                InlineKeyboardButton("За неделю", callback_data=f"parent_report_{student_id}_week"),
                InlineKeyboardButton("За месяц", callback_data=f"parent_report_{student_id}_month")
            ],
            [
                InlineKeyboardButton("За год", callback_data=f"parent_report_{student_id}_year"),
                InlineKeyboardButton("Назад к списку учеников", callback_data="parent_back_students")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.edit_message_text(
                f"{report_result['message']}\n\nВыберите другой период или вернитесь к списку учеников.",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"{report_result['message']}\n\nВыберите другой период или вернитесь к списку учеников.",
                reply_markup=reply_markup
            )
        return

    # Форматируем отчет
    student_name = report_result["student_name"]
    period_name = get_period_name(period)
    stats = report_result["stats"]

    report_text = f"📊 *Отчет об успеваемости ученика {student_name}*\n"
    report_text += f"*Период:* {period_name}\n\n"

    report_text += f"*Общие данные:*\n"
    report_text += f"• Пройдено тестов: {stats['total_tests']}\n"
    report_text += f"• Средний результат: {stats['average_score']}%\n"
    report_text += f"• Лучший результат: {stats['best_result']['score']}% "
    report_text += f"({stats['best_result']['topic']}, {stats['best_result']['date']})\n"
    report_text += f"• Худший результат: {stats['worst_result']['score']}% "
    report_text += f"({stats['worst_result']['topic']}, {stats['worst_result']['date']})\n"
    report_text += f"• Общее время: {format_time(stats['total_time_spent'])}\n\n"

    report_text += f"*Изученные темы ({len(stats['topics_studied'])}):\n*"
    for topic in stats['topics_studied']:
        report_text += f"• {topic}\n"

    # Кнопки для выбора другого периода и возврата
    keyboard = [
        [
            InlineKeyboardButton("За неделю", callback_data=f"parent_report_{student_id}_week"),
            InlineKeyboardButton("За месяц", callback_data=f"parent_report_{student_id}_month")
        ],
        [
            InlineKeyboardButton("За год", callback_data=f"parent_report_{student_id}_year"),
            InlineKeyboardButton("Назад к списку учеников", callback_data="parent_back_students")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем отчет
    if query:
        await query.edit_message_text(
            report_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            report_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    # Отправляем график
    if "chart" in report_result:
        if query:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=report_result["chart"],
                caption=f"📈 Динамика успеваемости ученика {student_name} {period_name}"
            )
        else:
            await update.message.reply_photo(
                photo=report_result["chart"],
                caption=f"📈 Динамика успеваемости ученика {student_name} {period_name}"
            )


async def show_student_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, student_id: int, student_name: str,
                                query=None) -> None:
    """Показ и редактирование настроек для ученика"""
    user_id = update.effective_user.id

    # Получаем текущие настройки
    settings_result = parent_service.get_parent_settings(user_id)

    if not settings_result["success"]:
        if query:
            await query.edit_message_text(f"Ошибка получения настроек: {settings_result['message']}")
        else:
            await update.message.reply_text(f"Ошибка получения настроек: {settings_result['message']}")
        return

    settings = settings_result["settings"]

    # Получаем настройки для конкретного ученика
    if "student_notifications" not in settings:
        settings["student_notifications"] = {}

    if str(student_id) not in settings["student_notifications"]:
        settings["student_notifications"][str(student_id)] = {}

    student_settings = settings["student_notifications"][str(student_id)]

    # Значения по умолчанию
    weekly_reports = student_settings.get("weekly_reports", False)
    test_completion = student_settings.get("test_completion", False)
    low_score_threshold = student_settings.get("low_score_threshold", 60)
    high_score_threshold = student_settings.get("high_score_threshold", 90)

    # Форматируем сообщение с настройками
    settings_text = f"⚙️ *Настройки уведомлений для ученика {student_name}*\n\n"

    settings_text += "*Текущие настройки:*\n"
    settings_text += f"• Еженедельные отчеты: {'✅ Включено' if weekly_reports else '❌ Выключено'}\n"
    settings_text += f"• Уведомления о завершении тестов: {'✅ Включено' if test_completion else '❌ Выключено'}\n"
    settings_text += f"• Порог низкого результата: {low_score_threshold}%\n"
    settings_text += f"• Порог высокого результата: {high_score_threshold}%\n\n"

    settings_text += "Используйте кнопки ниже для изменения настроек."

    # Создаем клавиатуру для редактирования настроек
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'Отключить' if weekly_reports else 'Включить'} еженедельные отчеты",
                callback_data=f"parent_toggle_weekly_reports_{student_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'Отключить' if test_completion else 'Включить'} уведомления о тестах",
                callback_data=f"parent_toggle_test_completion_{student_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"Порог низкого результата: {low_score_threshold}%",
                callback_data=f"parent_threshold_low_score_threshold_{student_id}_none"
            )
        ],
        [
            InlineKeyboardButton(
                "▼",
                callback_data=f"parent_threshold_low_score_threshold_{student_id}_down"
            ),
            InlineKeyboardButton(
                "▲",
                callback_data=f"parent_threshold_low_score_threshold_{student_id}_up"
            )
        ],
        [
            InlineKeyboardButton(
                f"Порог высокого результата: {high_score_threshold}%",
                callback_data=f"parent_threshold_high_score_threshold_{student_id}_none"
            )
        ],
        [
            InlineKeyboardButton(
                "▼",
                callback_data=f"parent_threshold_high_score_threshold_{student_id}_down"
            ),
            InlineKeyboardButton(
                "▲",
                callback_data=f"parent_threshold_high_score_threshold_{student_id}_up"
            )
        ],
        [
            InlineKeyboardButton(
                "Назад к списку учеников",
                callback_data="parent_back_students"
            )
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Отправляем или обновляем сообщение
    if query:
        await query.edit_message_text(
            settings_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            settings_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )


# Вспомогательные функции

def get_period_name(period: str) -> str:
    """Получение читаемого названия периода"""
    periods = {
        "week": "за неделю",
        "month": "за месяц",
        "year": "за год",
        "all": "за всё время"
    }
    return periods.get(period, "за всё время")


def format_time(minutes: int) -> str:
    """Форматирование времени из минут в часы и минуты"""
    hours = minutes // 60
    mins = minutes % 60

    if hours > 0:
        return f"{hours} ч {mins} мин"
    else:
        return f"{mins} мин"