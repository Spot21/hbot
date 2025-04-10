import logging
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy.exc import IntegrityError

from services.stats_service import generate_topic_analytics
from database.models import User, Topic, Question
from database.db_manager import get_session
from config import ADMINS

logger = logging.getLogger(__name__)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /admin для открытия панели администратора"""
    user_id = update.effective_user.id

    # Проверяем, является ли пользователь администратором
    if str(user_id) not in ADMINS:
        await update.message.reply_text(
            "У вас нет прав для доступа к панели администратора."
        )
        return

    # Создаем клавиатуру админ-панели
    keyboard = [
        [
            InlineKeyboardButton("📊 Статистика по темам", callback_data="admin_topic_stats"),
            InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("➕ Добавить вопрос", callback_data="admin_add_question"),
            InlineKeyboardButton("📁 Импорт вопросов", callback_data="admin_import")
        ],
        [
            InlineKeyboardButton("✏️ Редактировать темы", callback_data="admin_edit_topics"),
            InlineKeyboardButton("⚙️ Настройки бота", callback_data="admin_settings")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👨‍💻 *Панель администратора*\n\n"
        "Выберите действие из списка ниже:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def add_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /add_question для добавления нового вопроса"""
    user_id = update.effective_user.id

    # Проверяем, является ли пользователь администратором
    if str(user_id) not in ADMINS:
        await update.message.reply_text(
            "У вас нет прав для добавления вопросов."
        )
        return

    # Получаем список тем для выбора
    with get_session() as session:
        topics = session.query(Topic).all()

    if not topics:
        await update.message.reply_text(
            "Сначала необходимо создать хотя бы одну тему. Используйте /admin -> Редактировать темы."
        )
        return

    # Создаем клавиатуру с выбором темы
    keyboard = []
    for topic in topics:
        keyboard.append([
            InlineKeyboardButton(
                topic.name,
                callback_data=f"admin_select_topic_{topic.id}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Выберите тему для нового вопроса:",
        reply_markup=reply_markup
    )

    # Устанавливаем состояние для пользователя
    context.user_data["admin_state"] = "adding_question"


async def import_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /import для импорта вопросов из JSON файла"""
    user_id = update.effective_user.id

    # Проверяем, является ли пользователь администратором
    if str(user_id) not in ADMINS:
        await update.message.reply_text(
            "У вас нет прав для импорта вопросов."
        )
        return

    await update.message.reply_text(
        "Для импорта вопросов отправьте JSON файл с вопросами.\n\n"
        "Структура файла должна соответствовать формату:\n"
        "```\n"
        "{\n"
        '  "topic": {\n'
        '    "id": 1,\n'
        '    "name": "Название темы",\n'
        '    "description": "Описание темы"\n'
        "  },\n"
        '  "questions": [\n'
        "    {\n"
        '      "id": 1,\n'
        '      "text": "Текст вопроса",\n'
        '      "options": ["Вариант 1", "Вариант 2", ...],\n'
        '      "correct_answer": [0],\n'
        '      "question_type": "single",\n'
        '      "difficulty": 1,\n'
        '      "explanation": "Объяснение ответа"\n'
        "    },\n"
        "    ...\n"
        "  ]\n"
        "}\n"
        "```\n\n"
        "Или просто используйте команду /admin и выберите 'Импорт вопросов'.",
        parse_mode="Markdown"
    )

    # Устанавливаем состояние для пользователя
    context.user_data["admin_state"] = "importing_questions"


async def handle_admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий кнопок в панели администратора"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Проверяем, является ли пользователь администратором
    if str(user_id) not in ADMINS:
        await query.edit_message_text(
            "У вас нет прав для доступа к панели администратора."
        )
        return

    try:
        # Используем контекстный менеджер для всех операций с базой данных
        if query.data == "admin_topic_stats":
            # Показываем статистику по темам
            await show_topic_stats(update, context)


        elif query.data == "admin_users":
            # Показываем список пользователей
            await show_users_list(update, context)

        elif query.data == "admin_add_question":
            # Переход к добавлению вопроса
            with get_session() as session:
                topics = session.query(Topic).all()

                # Важно: создаем копию данных, а не используем объекты из сессии напрямую
                topics_data = [{"id": topic.id, "name": topic.name} for topic in topics]

            if not topics_data:
                await query.edit_message_text(
                    "Сначала необходимо создать хотя бы одну тему. Используйте 'Редактировать темы'."
                )
                return

            # Создаем клавиатуру с выбором темы
            keyboard = []
            for topic in topics_data:
                keyboard.append([
                    InlineKeyboardButton(
                        topic["name"],
                        callback_data=f"admin_select_topic_{topic['id']}"
                    )
                ])

            # Добавляем кнопку возврата
            keyboard.append([
                InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "Выберите тему для нового вопроса:",
                reply_markup=reply_markup
            )

            # Устанавливаем состояние для пользователя
            context.user_data["admin_state"] = "adding_question"

        elif query.data == "admin_import":
            # Инструкция по импорту вопросов
            await query.edit_message_text(
                "Для импорта вопросов отправьте JSON файл с вопросами.\n\n"
                "Структура файла должна соответствовать формату:\n"
                "```\n"
                "{\n"
                '  "topic": {\n'
                '    "id": 1,\n'
                '    "name": "Название темы",\n'
                '    "description": "Описание темы"\n'
                "  },\n"
                '  "questions": [\n'
                "    {\n"
                '      "id": 1,\n'
                '      "text": "Текст вопроса",\n'
                '      "options": ["Вариант 1", "Вариант 2", ...],\n'
                '      "correct_answer": [0],\n'
                '      "question_type": "single",\n'
                '      "difficulty": 1,\n'
                '      "explanation": "Объяснение ответа"\n'
                "    },\n"
                "    ...\n"
                "  ]\n"
                "}\n"
                "```\n\n"
                "Отправьте файл как документ в этот чат.",
                parse_mode="Markdown"
            )

            # Устанавливаем состояние для пользователя
            context.user_data["admin_state"] = "importing_questions"

        elif query.data == "admin_edit_topics":
            # Редактирование тем
            await show_topics_list(update, context)

        elif query.data == "admin_settings":
            # Настройки бота
            await show_bot_settings(update, context)

        elif query.data == "admin_setting_questions_count":
            # Обработка настройки количества вопросов в тесте
            await query.edit_message_text(
                "Укажите количество вопросов в тесте по умолчанию (от 5 до 20):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("5", callback_data="admin_set_questions_5"),
                     InlineKeyboardButton("10", callback_data="admin_set_questions_10"),
                     InlineKeyboardButton("15", callback_data="admin_set_questions_15"),
                     InlineKeyboardButton("20", callback_data="admin_set_questions_20")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")]
                ])
            )

        elif query.data == "admin_setting_reports":
            # Обработка настройки отчетов родителям
            from config import ENABLE_PARENT_REPORTS
            current_state = "включены" if ENABLE_PARENT_REPORTS else "отключены"

            await query.edit_message_text(
                f"Автоматические отчеты родителям сейчас {current_state}.\n\n"
                "Выберите действие:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Включить", callback_data="admin_reports_enable"),
                     InlineKeyboardButton("❌ Отключить", callback_data="admin_reports_disable")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")]
                ])
            )

        elif query.data.startswith("admin_set_questions_"):
            # Установка количества вопросов
            try:
                questions_count = int(query.data.replace("admin_set_questions_", ""))

                # Здесь код для сохранения настройки
                # Например, через изменение переменной окружения или config файла

                await query.edit_message_text(
                    f"✅ Количество вопросов в тесте установлено: {questions_count}\n\n"
                    "Настройка будет применена при следующем запуске бота.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад к настройкам", callback_data="admin_settings")
                    ]])
                )
            except ValueError:
                await query.edit_message_text(
                    "Произошла ошибка при установке количества вопросов.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")
                    ]])
                )

        elif query.data.startswith("admin_reports_"):
            # Включение/отключение отчетов
            action = query.data.replace("admin_reports_", "")

            try:
                # Здесь код для изменения настройки
                # Например, через изменение переменной окружения или config файла
                new_state = "включены" if action == "enable" else "отключены"

                await query.edit_message_text(
                    f"✅ Автоматические отчеты родителям {new_state}.\n\n"
                    "Настройка будет применена при следующем запуске бота.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад к настройкам", callback_data="admin_settings")
                    ]])
                )
            except Exception as e:
                await query.edit_message_text(
                    f"Произошла ошибка при изменении настроек: {str(e)}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")
                    ]])
                )
        elif query.data == "admin_settings":
            await show_bot_settings(update, context)

        elif query.data.startswith("admin_select_topic_"):
            # Выбор темы для нового вопроса
            topic_id = int(query.data.replace("admin_select_topic_", ""))
            context.user_data["selected_topic_id"] = topic_id

            # Предлагаем выбрать тип вопроса
            keyboard = [
                [
                    InlineKeyboardButton("Одиночный выбор", callback_data="admin_question_type_single"),
                    InlineKeyboardButton("Множественный выбор", callback_data="admin_question_type_multiple")
                ],
                [
                    InlineKeyboardButton("Последовательность", callback_data="admin_question_type_sequence"),
                    InlineKeyboardButton("🔙 Назад", callback_data="admin_back_topics")
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "Выберите тип вопроса:",
                reply_markup=reply_markup
            )

        elif query.data.startswith("admin_question_type_"):
            # Выбор типа вопроса
            question_type = query.data.replace("admin_question_type_", "")
            context.user_data["question_type"] = question_type

            # Предлагаем ввести текст вопроса
            await query.edit_message_text(
                "Отправьте текст вопроса в следующем сообщении."
            )

            # Обновляем состояние
            context.user_data["admin_state"] = "entering_question_text"

        elif query.data == "admin_back_main":
            # Возврат в главное меню администратора
            await show_admin_panel(update, context)

        elif query.data == "admin_back_topics":
            # Возврат к списку тем
            with get_session() as session:
                topics = session.query(Topic).all()

            if not topics:
                await query.edit_message_text(
                    "Сначала необходимо создать хотя бы одну тему. Используйте 'Редактировать темы'."
                )
                return

            # Создаем клавиатуру с выбором темы
            keyboard = []
            for topic in topics:
                keyboard.append([
                    InlineKeyboardButton(
                        topic.name,
                        callback_data=f"admin_select_topic_{topic.id}"
                    )
                ])

            # Добавляем кнопку возврата
            keyboard.append([
                InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "Выберите тему для нового вопроса:",
                reply_markup=reply_markup
            )

        elif query.data.startswith("admin_add_topic"):
            # Добавление новой темы
            await query.edit_message_text(
                "Отправьте название и описание новой темы в формате:\n\n"
                "Название темы\n"
                "Описание темы"
            )

            # Устанавливаем состояние для пользователя
            context.user_data["admin_state"] = "adding_topic"

        elif query.data.startswith("admin_edit_topic_"):
            # Редактирование выбранной темы
            topic_id = int(query.data.replace("admin_edit_topic_", ""))

            with get_session() as session:
                topic = session.query(Topic).get(topic_id)

                if not topic:
                    await query.edit_message_text(
                        "Тема не найдена."
                    )
                    return

                # Создаем клавиатуру с действиями
                keyboard = [
                    [
                        InlineKeyboardButton("✏️ Изменить название", callback_data=f"admin_edit_topic_name_{topic_id}"),
                        InlineKeyboardButton("📝 Изменить описание", callback_data=f"admin_edit_topic_desc_{topic_id}")
                    ],
                    [
                        InlineKeyboardButton("❌ Удалить тему", callback_data=f"admin_delete_topic_{topic_id}"),
                        InlineKeyboardButton("🔙 Назад", callback_data="admin_back_topics_list")
                    ]
                ]

                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    f"*Редактирование темы:* {topic.name}\n\n"
                    f"*Описание:* {topic.description or 'Нет описания'}\n\n"
                    "Выберите действие:",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

        elif query.data == "admin_back_topics_list":
            # Возврат к списку тем
            await show_topics_list(update, context)

    except Exception as e:
        logger.error(f"Error in handle_admin_button: {e}")
        await query.edit_message_text(
            f"Произошла ошибка при обработке запроса: {str(e)}"
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик загрузки документов (для импорта вопросов)"""
    user_id = update.effective_user.id

    # Проверяем, является ли пользователь администратором
    if str(user_id) not in ADMINS:
        await update.message.reply_text(
            "У вас нет прав для импорта вопросов."
        )
        return

    # Проверяем, ожидается ли загрузка файла
    if context.user_data.get("admin_state") != "importing_questions":
        return

    # Проверяем тип документа
    document = update.message.document
    if not document.file_name.endswith('.json'):
        await update.message.reply_text(
            "Пожалуйста, загрузите файл в формате JSON."
        )
        return

    try:
        # Скачиваем файл
        file = await context.bot.get_file(document.file_id)
        file_path = f"downloads/{document.file_name}"
        os.makedirs("downloads", exist_ok=True)
        await file.download_to_drive(file_path)

        # Обрабатываем файл
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Импортируем вопросы
        result = import_questions_from_json(data)

        # Удаляем временный файл
        os.remove(file_path)

        if result["success"]:
            await update.message.reply_text(
                f"✅ Импорт успешно завершен!\n\n"
                f"• Добавлена тема: {result['topic_name']}\n"
                f"• Импортировано вопросов: {result['questions_count']}"
            )
        else:
            await update.message.reply_text(
                f"❌ Ошибка при импорте: {result['message']}"
            )

    except Exception as e:
        logger.error(f"Error importing questions: {e}")
        await update.message.reply_text(
            f"Произошла ошибка при обработке файла: {str(e)}"
        )

    # Сбрасываем состояние
    context.user_data.pop("admin_state", None)


async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений от администратора в процессе редактирования"""
    user_id = update.effective_user.id
    message_text = update.message.text

    # Проверяем, является ли пользователь администратором
    if str(user_id) not in ADMINS:
        await update.message.reply_text(
            "У вас нет прав для выполнения этой операции."
        )
        return

    # Проверяем состояние
    state = context.user_data.get("admin_state", None)

    if state == "entering_question_text":
        # Сохраняем текст вопроса
        context.user_data["question_text"] = message_text

        # Запрашиваем варианты ответов
        await update.message.reply_text(
            "Отправьте варианты ответов, каждый с новой строки. Например:\n\n"
            "Вариант 1\n"
            "Вариант 2\n"
            "Вариант 3"
        )

        # Обновляем состояние
        context.user_data["admin_state"] = "entering_options"

    elif state == "entering_options":
        # Разбиваем сообщение на строки для получения вариантов
        options = [opt.strip() for opt in message_text.split('\n') if opt.strip()]

        if len(options) < 2:
            await update.message.reply_text(
                "Необходимо указать минимум 2 варианта ответа. Пожалуйста, попробуйте еще раз."
            )
            return

        # Сохраняем варианты ответов
        context.user_data["options"] = options

        # Запрашиваем правильный ответ в зависимости от типа вопроса
        question_type = context.user_data.get("question_type", "single")

        if question_type == "single":
            # Показываем варианты ответов с номерами
            options_text = "\n".join([f"{i + 1}. {opt}" for i, opt in enumerate(options)])

            await update.message.reply_text(
                f"Выберите номер правильного варианта ответа (от 1 до {len(options)}):\n\n{options_text}"
            )

            context.user_data["admin_state"] = "entering_correct_answer_single"

        elif question_type == "multiple":
            # Показываем варианты ответов с номерами
            options_text = "\n".join([f"{i + 1}. {opt}" for i, opt in enumerate(options)])

            await update.message.reply_text(
                f"Укажите номера правильных вариантов ответов через запятую (например, 1,3,4):\n\n{options_text}"
            )

            context.user_data["admin_state"] = "entering_correct_answer_multiple"

        elif question_type == "sequence":
            # Показываем варианты ответов с номерами
            options_text = "\n".join([f"{i + 1}. {opt}" for i, opt in enumerate(options)])

            await update.message.reply_text(
                f"Укажите правильную последовательность вариантов через запятую (например, 3,1,4,2):\n\n{options_text}"
            )

            context.user_data["admin_state"] = "entering_correct_answer_sequence"

    elif state == "entering_correct_answer_single":
        try:
            # Преобразуем ответ в индекс (с учетом, что нумерация начинается с 1)
            answer_index = int(message_text.strip()) - 1
            options = context.user_data.get("options", [])

            if answer_index < 0 or answer_index >= len(options):
                await update.message.reply_text(
                    f"Указан неверный номер. Пожалуйста, выберите число от 1 до {len(options)}."
                )
                return

            # Сохраняем правильный ответ
            context.user_data["correct_answer"] = [answer_index]

            # Запрашиваем объяснение
            await update.message.reply_text(
                "Введите объяснение правильного ответа (или отправьте 'Нет' для пропуска этого шага):"
            )

            context.user_data["admin_state"] = "entering_explanation"

        except ValueError:
            await update.message.reply_text(
                "Пожалуйста, введите число. Попробуйте еще раз."
            )

    elif state == "entering_correct_answer_multiple":
        try:
            # Разбиваем ответ на индексы
            answer_indices = [int(idx.strip()) - 1 for idx in message_text.split(',')]
            options = context.user_data.get("options", [])

            # Проверяем корректность индексов
            for idx in answer_indices:
                if idx < 0 or idx >= len(options):
                    await update.message.reply_text(
                        f"Указан неверный номер: {idx + 1}. Пожалуйста, выберите числа от 1 до {len(options)}."
                    )
                    return

            # Сохраняем правильные ответы
            context.user_data["correct_answer"] = answer_indices

            # Запрашиваем объяснение
            await update.message.reply_text(
                "Введите объяснение правильного ответа (или отправьте 'Нет' для пропуска этого шага):"
            )

            context.user_data["admin_state"] = "entering_explanation"

        except ValueError:
            await update.message.reply_text(
                "Пожалуйста, введите числа через запятую. Попробуйте еще раз."
            )

    elif state == "entering_correct_answer_sequence":
        try:
            # Разбиваем ответ на индексы
            sequence = [int(idx.strip()) - 1 for idx in message_text.split(',')]
            options = context.user_data.get("options", [])

            # Проверяем корректность индексов и их уникальность
            if len(sequence) != len(options) or len(set(sequence)) != len(options):
                await update.message.reply_text(
                    f"Необходимо указать уникальные номера для всех {len(options)} вариантов."
                )
                return

            for idx in sequence:
                if idx < 0 or idx >= len(options):
                    await update.message.reply_text(
                        f"Указан неверный номер: {idx + 1}. Пожалуйста, выберите числа от 1 до {len(options)}."
                    )
                    return

            # Преобразуем индексы в строки для единообразия с форматом хранения
            sequence_str = [str(idx) for idx in sequence]

            # Сохраняем правильную последовательность
            context.user_data["correct_answer"] = sequence_str

            # Запрашиваем объяснение
            await update.message.reply_text(
                "Введите объяснение правильного ответа (или отправьте 'Нет' для пропуска этого шага):"
            )

            context.user_data["admin_state"] = "entering_explanation"

        except ValueError:
            await update.message.reply_text(
                "Пожалуйста, введите числа через запятую. Попробуйте еще раз."
            )

    elif state == "entering_explanation":
        # Сохраняем объяснение, если оно не "Нет"
        explanation = None if message_text.lower() == "нет" else message_text

        # Собираем все данные для создания вопроса
        question_data = {
            "topic_id": context.user_data.get("selected_topic_id"),
            "text": context.user_data.get("question_text"),
            "options": context.user_data.get("options"),
            "correct_answer": context.user_data.get("correct_answer"),
            "question_type": context.user_data.get("question_type"),
            "explanation": explanation
        }

        # Создаем новый вопрос
        result = add_question_to_db(question_data)

        if result["success"]:
            await update.message.reply_text(
                "✅ Вопрос успешно добавлен!"
            )

            # Спрашиваем, хочет ли администратор добавить еще один вопрос
            keyboard = [
                [
                    InlineKeyboardButton("➕ Добавить еще вопрос", callback_data="admin_add_question"),
                    InlineKeyboardButton("🔙 Вернуться в меню", callback_data="admin_back_main")
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "Выберите дальнейшее действие:",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"❌ Ошибка при добавлении вопроса: {result['message']}"
            )

        # Сбрасываем состояние
        context.user_data.pop("admin_state", None)

    elif state == "adding_topic":
        # Разбиваем сообщение на строки
        lines = message_text.strip().split('\n')

        if not lines:
            await update.message.reply_text(
                "Пожалуйста, введите название темы."
            )
            return

        # Первая строка - название темы
        topic_name = lines[0].strip()

        # Остальные строки (если есть) - описание
        topic_description = '\n'.join(lines[1:]).strip() if len(lines) > 1 else None

        # Создаем новую тему
        result = add_topic_to_db(topic_name, topic_description)

        if result["success"]:
            await update.message.reply_text(
                f"✅ Тема '{topic_name}' успешно добавлена!"
            )

            # Показываем обновленный список тем
            await show_topics_list(update, context)
        else:
            await update.message.reply_text(
                f"❌ Ошибка при добавлении темы: {result['message']}"
            )

        # Сбрасываем состояние
        context.user_data.pop("admin_state", None)

    else:
        await update.message.reply_text(
            "Неизвестная команда. Пожалуйста, используйте панель администратора."
        )


def import_questions_from_json(data: dict) -> dict:
    """Импорт вопросов из JSON"""
    try:
        # Проверяем структуру данных
        if "topic" not in data or "questions" not in data:
            return {"success": False, "message": "Неверная структура JSON. Должны быть поля 'topic' и 'questions'."}

        topic_data = data["topic"]
        questions_data = data["questions"]

        with get_session() as session:
            # Создаем или обновляем тему
            topic = session.query(Topic).filter(Topic.id == topic_data.get("id")).first()

            if not topic:
                # Если темы с таким ID нет, создаем новую
                topic = Topic(
                    name=topic_data["name"],
                    description=topic_data.get("description", "")
                )
                session.add(topic)
                session.flush()  # Чтобы получить ID
            else:
                # Если тема существует, обновляем её
                topic.name = topic_data["name"]
                topic.description = topic_data.get("description", topic.description)

            # Добавляем вопросы
            questions_count = 0
            for q_data in questions_data:
                # Проверяем, существует ли уже вопрос с таким ID в этой теме
                question = session.query(Question).filter(
                    Question.topic_id == topic.id,
                    Question.id == q_data.get("id")
                ).first()

                if not question:
                    # Создаем новый вопрос
                    question = Question(
                        topic_id=topic.id,
                        text=q_data["text"],
                        options=json.dumps(q_data["options"]),
                        correct_answer=json.dumps(q_data["correct_answer"]),
                        question_type=q_data["question_type"],
                        difficulty=q_data.get("difficulty", 1),
                        media_url=q_data.get("media_url"),
                        explanation=q_data.get("explanation", "")
                    )
                    session.add(question)
                else:
                    # Обновляем существующий вопрос
                    question.text = q_data["text"]
                    question.options = json.dumps(q_data["options"])
                    question.correct_answer = json.dumps(q_data["correct_answer"])
                    question.question_type = q_data["question_type"]
                    question.difficulty = q_data.get("difficulty", question.difficulty)
                    question.media_url = q_data.get("media_url", question.media_url)
                    question.explanation = q_data.get("explanation", question.explanation)

                questions_count += 1

            # Сохраняем изменения
            session.commit()

            return {
                "success": True,
                "topic_name": topic.name,
                "questions_count": questions_count
            }

    except Exception as e:
        logger.error(f"Error in import_questions_from_json: {e}")
        return {"success": False, "message": str(e)}


def add_question_to_db(data: dict) -> dict:
    """Добавление нового вопроса в базу данных"""
    try:
        # Проверяем наличие необходимых полей
        required_fields = ["topic_id", "text", "options", "correct_answer", "question_type"]
        for field in required_fields:
            if field not in data or data[field] is None:
                return {"success": False, "message": f"Отсутствует обязательное поле: {field}"}

        with get_session() as session:
            # Проверяем существование темы
            topic = session.query(Topic).get(data["topic_id"])
            if not topic:
                return {"success": False, "message": "Указанная тема не существует"}

            # Создаем новый вопрос
            question = Question(
                topic_id=data["topic_id"],
                text=data["text"],
                options=json.dumps(data["options"]),
                correct_answer=json.dumps(data["correct_answer"]),
                question_type=data["question_type"],
                difficulty=data.get("difficulty", 1),
                media_url=data.get("media_url"),
                explanation=data.get("explanation", "")
            )

            session.add(question)
            session.commit()

            return {"success": True, "question_id": question.id}

    except Exception as e:
        logger.error(f"Error in add_question_to_db: {e}")
        return {"success": False, "message": str(e)}


def add_topic_to_db(name: str, description: str = None) -> dict:
    """Добавление новой темы в базу данных"""
    try:
        # Проверяем название
        if not name or len(name.strip()) < 3:
            return {"success": False, "message": "Название темы должно содержать минимум 3 символа"}

        with get_session() as session:
            # Проверяем уникальность названия
            existing_topic = session.query(Topic).filter(Topic.name == name).first()
            if existing_topic:
                return {"success": False, "message": f"Тема с названием '{name}' уже существует"}

            # Создаем новую тему
            topic = Topic(
                name=name,
                description=description
            )

            session.add(topic)
            session.commit()

            return {"success": True, "topic_id": topic.id}

    except Exception as e:
        logger.error(f"Error in add_topic_to_db: {e}")
        return {"success": False, "message": str(e)}


async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ панели администратора"""
    query = update.callback_query

    # Создаем клавиатуру админ-панели
    keyboard = [
        [
            InlineKeyboardButton("📊 Статистика по темам", callback_data="admin_topic_stats"),
            InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("➕ Добавить вопрос", callback_data="admin_add_question"),
            InlineKeyboardButton("📁 Импорт вопросов", callback_data="admin_import")
        ],
        [
            InlineKeyboardButton("✏️ Редактировать темы", callback_data="admin_edit_topics"),
            InlineKeyboardButton("⚙️ Настройки бота", callback_data="admin_settings")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "👨‍💻 *Панель администратора*\n\n"
        "Выберите действие из списка ниже:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def show_topic_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ статистики по темам"""
    query = update.callback_query

    # Получаем статистику по темам
    stats = generate_topic_analytics()

    if not stats["success"]:
        await query.edit_message_text(
            f"Ошибка получения статистики: {stats['message']}\n\n"
            "Нажмите /admin для возврата в панель администратора."
        )
        return

    if not stats["has_data"]:
        await query.edit_message_text(
            "Нет данных для анализа. Необходимо, чтобы ученики прошли хотя бы один тест.\n\n"
            "Нажмите /admin для возврата в панель администратора."
        )
        return

    try:
        # Форматируем текст со статистикой
        stats_text = "📊 *Статистика по темам*\n\n"

        # Добавляем информацию о самых сложных и простых темах
        topic_stats = stats["topic_stats"]
        stats_text += "*Сложность тем (от самой сложной к самой простой):*\n"

        for i, topic in enumerate(topic_stats):
            emoji = "🔴" if i < 2 else "🟡" if i < len(topic_stats) - 2 else "🟢"
            stats_text += f"{emoji} {topic['topic_name']}: {topic['avg_score']}% (пройдено тестов: {topic['tests_count']})\n"

        # Кнопка для возврата
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Отправляем текст статистики
        await query.edit_message_text(
            stats_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

        # Отправляем график
        if "chart" in stats:
            await context.bot.send_photo(
                chat_id=update.effective_user.id,
                photo=stats["chart"],
                caption="📊 Средний результат по темам (от самых сложных к самым простым)"
            )
    except Exception as e:
        logger.error(f"Error in show_topic_stats: {e}")
        await query.edit_message_text(
            f"Произошла ошибка при отображении статистики: {str(e)}\n\n"
            "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
        )


async def show_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ списка пользователей"""
    query = update.callback_query

    try:
        with get_session() as session:
            # Получаем статистику по пользователям
            students_count = session.query(User).filter(User.role == "student").count()
            parents_count = session.query(User).filter(User.role == "parent").count()
            admins_count = session.query(User).filter(User.role == "admin").count()

            # Получаем список последних активных пользователей
            # Важно: создаем копии данных, а не используем объекты сессии напрямую
            recent_users = []
            for user in session.query(User).order_by(User.last_active.desc()).limit(10).all():
                recent_users.append({
                    "role": user.role,
                    "full_name": user.full_name,
                    "username": user.username,
                    "telegram_id": user.telegram_id,
                    "last_active": user.last_active
                })

        # Форматируем текст со статистикой
        users_text = "👥 *Статистика пользователей*\n\n"
        users_text += f"• Всего учеников: {students_count}\n"
        users_text += f"• Всего родителей: {parents_count}\n"
        users_text += f"• Всего администраторов: {admins_count}\n\n"

        users_text += "*Недавняя активность:*\n"
        for user_data in recent_users:
            role_emoji = "👨‍🎓" if user_data["role"] == "student" else "👨‍👩‍👧‍👦" if user_data["role"] == "parent" else "👨‍💻"
            name = user_data["full_name"] or user_data["username"] or f"Пользователь {user_data['telegram_id']}"
            last_active = user_data["last_active"].strftime('%d.%m.%Y %H:%M')
            users_text += f"{role_emoji} {name} - {last_active}\n"

        # Кнопки для действий с пользователями и возврата
        keyboard = [
            [
                InlineKeyboardButton("👨‍🎓 Ученики", callback_data="admin_list_students"),
                InlineKeyboardButton("👨‍👩‍👧‍👦 Родители", callback_data="admin_list_parents")
            ],
            [
                InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            users_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in show_users_list: {e}")
        await query.edit_message_text(
            f"Произошла ошибка при получении списка пользователей: {str(e)}\n\n"
            "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
        )


async def show_topics_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ списка тем для редактирования"""
    query = update.callback_query

    try:
        with get_session() as session:
            # Получаем список тем с созданием копии данных
            topics_data = []
            for topic in session.query(Topic).all():
                topics_data.append({
                    "id": topic.id,
                    "name": topic.name,
                    "description": topic.description
                })

        # Форматируем текст со списком тем
        topics_text = "✏️ *Темы для тестирования*\n\n"

        if not topics_data:
            topics_text += "Список тем пуст. Создайте первую тему."
        else:
            for topic in topics_data:
                topics_text += f"• *{topic['name']}*\n"
                if topic['description']:
                    topics_text += f"  _{topic['description']}_\n"

        # Кнопки для добавления темы и возврата
        keyboard = [
            [
                InlineKeyboardButton("➕ Добавить тему", callback_data="admin_add_topic")
            ]
        ]

        # Добавляем кнопки для редактирования существующих тем
        for topic in topics_data:
            keyboard.append([
                InlineKeyboardButton(f"✏️ {topic['name']}", callback_data=f"admin_edit_topic_{topic['id']}")
            ])

        # Добавляем кнопку возврата
        keyboard.append([
            InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            topics_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in show_topics_list: {e}")
        await query.edit_message_text(
            f"Произошла ошибка при получении списка тем: {str(e)}\n\n"
            "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
        )


async def show_bot_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ настроек бота"""
    query = update.callback_query

    from config import DEFAULT_QUESTIONS_COUNT, ENABLE_PARENT_REPORTS

    # Форматируем текст с настройками
    settings_text = "⚙️ *Настройки бота*\n\n"
    settings_text += "Здесь вы можете настроить общие параметры работы бота:\n\n"

    settings_text += "*Текущие настройки:*\n"
    settings_text += f"• Число вопросов в тесте по умолчанию: {DEFAULT_QUESTIONS_COUNT}\n"
    settings_text += f"• Автоматические отчеты родителям: {'Включено' if ENABLE_PARENT_REPORTS else 'Отключено'}\n\n"

    settings_text += "Выберите настройку для изменения:"

    # Кнопки для изменения настроек и возврата
    keyboard = [
        [
            InlineKeyboardButton("🔢 Число вопросов", callback_data="admin_setting_questions_count"),
            InlineKeyboardButton("📊 Отчеты родителям", callback_data="admin_setting_reports")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

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