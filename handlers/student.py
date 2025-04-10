import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from io import BytesIO

from services.quiz_service import QuizService
from services.stats_service import get_user_stats
from database.models import User
from database.db_manager import get_session

logger = logging.getLogger(__name__)
quiz_service = QuizService()


async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /test для начала тестирования"""
    try:
        user_id = update.effective_user.id

        # Получаем список доступных тем
        topics = quiz_service.get_topics()

        if not topics:
            await update.message.reply_text(
                "К сожалению, доступных тем для тестирования нет. Пожалуйста, попробуйте позже."
            )
            return

        # Создаем клавиатуру с выбором темы
        keyboard = []
        for topic in topics:
            keyboard.append([
                InlineKeyboardButton(
                    topic["name"],
                    callback_data=f"quiz_start_{topic['id']}"
                )
            ])

        # Добавляем кнопку случайной темы
        keyboard.append([
            InlineKeyboardButton(
                "🎲 Случайная тема",
                callback_data="quiz_start_random"
            )
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Выберите тему для тестирования:",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error in start_test: {e}")
        await update.message.reply_text(
            "Произошла ошибка при запуске теста. Пожалуйста, попробуйте еще раз позже."
        )


async def handle_test_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий кнопок при тестировании"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    try:
        if query.data.startswith("quiz_start_"):
            # Начало теста по выбранной теме
            topic_id_str = query.data.replace("quiz_start_", "")

            # Обрабатываем случайную тему
            if topic_id_str == "random":
                import random
                topics = quiz_service.get_topics()
                if not topics:
                    await query.edit_message_text("К сожалению, доступных тем нет.")
                    return
                topic = random.choice(topics)
                topic_id = topic["id"]
            else:
                topic_id = int(topic_id_str)

            # Начинаем тест
            quiz_data = quiz_service.start_quiz(user_id, topic_id)

            if not quiz_data["success"]:
                await query.edit_message_text(quiz_data["message"])
                return

            # Показываем первый вопрос
            await show_question(update, context)

        elif query.data.startswith("quiz_answer_"):
            # Обработка ответа на вопрос
            parts = query.data.split("_")
            question_id = int(parts[2])
            option_index = int(parts[3])

            current_question = quiz_service.get_current_question(user_id)

            if current_question and current_question["id"] == question_id:
                if current_question["question_type"] == "single":
                    # Для вопроса с одиночным выбором сразу отправляем ответ
                    result = quiz_service.submit_answer(user_id, question_id, option_index)

                    if result["success"]:
                        if result["is_completed"]:
                            # Тест завершен
                            await show_test_results(update, context, result["result"])
                        else:
                            # Показываем следующий вопрос
                            await show_question(update, context)
                    else:
                        await query.edit_message_text(result["message"])

                elif current_question["question_type"] == "multiple":
                    # Для вопроса с множественным выбором обновляем выбранные варианты
                    selected_options = quiz_service.active_quizzes[user_id]["answers"].get(str(question_id), [])

                    if option_index in selected_options:
                        selected_options.remove(option_index)
                    else:
                        selected_options.append(option_index)

                    quiz_service.active_quizzes[user_id]["answers"][str(question_id)] = selected_options

                    # Обновляем вопрос с отмеченными вариантами
                    await show_question(update, context, edit=True)

        elif query.data.startswith("quiz_seq_"):
            # Обработка выбора для вопроса с последовательностью
            parts = query.data.split("_")
            question_id = int(parts[2])
            option_index = int(parts[3])

            current_question = quiz_service.get_current_question(user_id)

            if current_question and current_question["id"] == question_id:
                # Добавляем вариант к последовательности
                sequence = quiz_service.active_quizzes[user_id]["answers"].get(str(question_id), [])
                sequence.append(str(option_index))
                quiz_service.active_quizzes[user_id]["answers"][str(question_id)] = sequence

                # Обновляем вопрос с текущей последовательностью
                await show_question(update, context, edit=True)

        elif query.data.startswith("quiz_reset_"):
            # Сброс текущей последовательности
            parts = query.data.split("_")
            question_id = int(parts[2])

            current_question = quiz_service.get_current_question(user_id)

            if current_question and current_question["id"] == question_id:
                # Сбрасываем последовательность
                quiz_service.active_quizzes[user_id]["answers"][str(question_id)] = []

                # Обновляем вопрос
                await show_question(update, context, edit=True)

        elif query.data.startswith("quiz_confirm_"):
            # Подтверждение ответа для вопроса с множественным выбором или последовательностью
            parts = query.data.split("_")
            question_id = int(parts[2])

            current_question = quiz_service.get_current_question(user_id)

            if current_question and current_question["id"] == question_id:
                answer = quiz_service.active_quizzes[user_id]["answers"].get(str(question_id), [])

                # Отправляем ответ
                result = quiz_service.submit_answer(user_id, question_id, answer)

                if result["success"]:
                    if result["is_completed"]:
                        # Тест завершен
                        await show_test_results(update, context, result["result"])
                    else:
                        # Показываем следующий вопрос
                        await show_question(update, context)
                else:
                    await query.edit_message_text(result["message"])

        elif query.data == "quiz_skip":
            # Пропуск текущего вопроса
            result = quiz_service.skip_question(user_id)

            if result["success"]:
                if result["is_completed"]:
                    # Тест завершен
                    await show_test_results(update, context, result["result"])
                else:
                    # Показываем следующий вопрос
                    await show_question(update, context)
            else:
                await query.edit_message_text(result["message"])

    except Exception as e:
        logger.error(f"Error in handle_test_button: {e}")
        await query.edit_message_text(
            "Произошла ошибка при обработке вашего ответа. Пожалуйста, попробуйте еще раз."
        )


async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False) -> None:
    """Отображение текущего вопроса"""
    query = update.callback_query
    user_id = update.effective_user.id

    # Получаем текущий вопрос
    current_question = quiz_service.get_current_question(user_id)

    if not current_question:
        # Если вопросов больше нет, завершаем тест
        result = quiz_service.complete_quiz(user_id)
        await show_test_results(update, context, result)
        return

    # Форматируем вопрос
    question_num = quiz_service.active_quizzes[user_id]["current_question"] + 1
    total_questions = len(quiz_service.active_quizzes[user_id]["questions"])

    question_text, reply_markup, media_file = quiz_service.format_question_message(
        current_question, question_num, total_questions
    )

    # Отправляем или обновляем сообщение с вопросом
    if edit and query:
        await query.edit_message_text(
            text=question_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        # Если есть медиа-файл, отправляем его
        if media_file:
            with open(media_file, 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=question_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        else:
            if query:
                await query.edit_message_text(
                    text=question_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=question_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )


async def show_test_results(update: Update, context: ContextTypes.DEFAULT_TYPE, result: dict) -> None:
    """Отображение результатов теста"""
    query = update.callback_query

    if not result["success"]:
        await query.edit_message_text(result["message"])
        return

    # Форматируем результаты
    correct_count = result["correct_count"]
    total_questions = result["total_questions"]
    percentage = result["percentage"]

    result_text = f"📊 *Результаты теста*\n\n"
    result_text += f"✅ Правильных ответов: {correct_count} из {total_questions}\n"
    result_text += f"📈 Процент успеха: {percentage}%\n\n"

    # Добавляем эмодзи в зависимости от результата
    if percentage >= 90:
        result_text += "🏆 Отличный результат! Так держать! 🏆"
    elif percentage >= 70:
        result_text += "👍 Хороший результат! Продолжай в том же духе!"
    elif percentage >= 50:
        result_text += "💪 Неплохо, но есть куда расти!"
    else:
        result_text += "📚 Стоит повторить материал и попробовать еще раз."

    # Добавляем информацию о новых достижениях
    if "new_achievements" in result and result["new_achievements"]:
        result_text += "\n\n🏅 *Новые достижения:*\n"
        for achievement in result["new_achievements"]:
            result_text += f"• {achievement['name']} - {achievement['description']} (+{achievement['points']} очков)\n"

    # Кнопки для дальнейших действий
    keyboard = [
        [
            InlineKeyboardButton("📋 Детальный анализ", callback_data="quiz_details"),
            InlineKeyboardButton("🔄 Пройти еще раз", callback_data=f"quiz_repeat_{result.get('topic_id', 0)}")
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="common_stats"),
            InlineKeyboardButton("🏆 Достижения", callback_data="common_achievements")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=result_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /stats для отображения статистики ученика"""
    user_id = update.effective_user.id

    # Получаем статистику за разные периоды
    period = context.args[0] if context.args else "all"
    if period not in ["week", "month", "year", "all"]:
        period = "all"

    stats = get_user_stats(user_id, period)

    if not stats["success"]:
        await update.message.reply_text(
            f"Не удалось получить статистику: {stats['message']}"
        )
        return

    if not stats["has_data"]:
        periods_keyboard = [
            [
                InlineKeyboardButton("За неделю", callback_data="common_stats_week"),
                InlineKeyboardButton("За месяц", callback_data="common_stats_month"),
                InlineKeyboardButton("За год", callback_data="common_stats_year"),
                InlineKeyboardButton("За всё время", callback_data="common_stats_all")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(periods_keyboard)

        await update.message.reply_text(
            stats["message"],
            reply_markup=reply_markup
        )
        return

    # Форматируем текст статистики
    stats_text = f"📊 *Статистика тестирования*\n"
    stats_text += f"*Период:* {get_period_name(period)}\n\n"

    # Общая статистика
    stats_data = stats["stats"]
    stats_text += f"*Общие данные:*\n"
    stats_text += f"• Пройдено тестов: {stats_data['total_tests']}\n"
    stats_text += f"• Средний результат: {stats_data['average_score']}%\n"
    stats_text += f"• Лучший результат: {stats_data['best_result']['score']}% "
    stats_text += f"({stats_data['best_result']['topic']}, {stats_data['best_result']['date']})\n"
    stats_text += f"• Общее время: {format_time(stats_data['total_time_spent'])}\n"

    # Динамика по времени
    if "time_stats" in stats and stats["time_stats"]:
        time_stats = stats["time_stats"]
        stats_text += f"\n*Динамика за период:*\n"
        progress_sign = "+" if time_stats["progress"] >= 0 else ""
        stats_text += f"• Изменение результата: {progress_sign}{time_stats['progress']}% "
        stats_text += f"({progress_sign}{time_stats['progress_percentage']}%)\n"

    # Статистика по темам
    if "tests_by_topic" in stats_data and stats_data["tests_by_topic"]:
        stats_text += f"\n*Тесты по темам:*\n"
        for topic, count in stats_data["tests_by_topic"].items():
            stats_text += f"• {topic}: {count} тестов\n"

    # Кнопки для выбора периода
    periods_keyboard = [
        [
            InlineKeyboardButton("За неделю", callback_data="common_stats_week"),
            InlineKeyboardButton("За месяц", callback_data="common_stats_month"),
            InlineKeyboardButton("За год", callback_data="common_stats_year"),
            InlineKeyboardButton("За всё время", callback_data="common_stats_all")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(periods_keyboard)

    # Отправляем текст статистики
    await update.message.reply_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    # Отправляем графики, если они есть
    if "charts" in stats and stats["charts"]:
        charts = stats["charts"]

        if "progress_chart" in charts:
            await update.message.reply_photo(
                photo=charts["progress_chart"],
                caption="📈 Динамика результатов по времени"
            )

        if "topics_chart" in charts:
            await update.message.reply_photo(
                photo=charts["topics_chart"],
                caption="📊 Средний результат по темам"
            )


async def show_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /achievements для отображения достижений ученика"""
    user_id = update.effective_user.id

    # Получаем статистику с достижениями
    stats = get_user_stats(user_id)

    if not stats["success"]:
        await update.message.reply_text(
            f"Не удалось получить информацию о достижениях: {stats['message']}"
        )
        return

    achievements = stats.get("achievements", [])
    total_points = stats.get("total_points", 0)

    if not achievements:
        await update.message.reply_text(
            "У вас пока нет достижений. Проходите тесты, чтобы получать награды!"
        )
        return

    # Форматируем текст с достижениями
    achievements_text = f"🏆 *Ваши достижения*\n\n"
    achievements_text += f"*Общее количество баллов:* {total_points}\n\n"

    for achievement in achievements:
        achievements_text += f"🏅 *{achievement['name']}*\n"
        achievements_text += f"_{achievement['description']}_\n"
        achievements_text += f"Получено: {achievement['achieved_at'].strftime('%d.%m.%Y')}\n"
        achievements_text += f"Баллы: +{achievement['points']}\n\n"

    # Кнопки для перехода к статистике и таблице лидеров
    keyboard = [
        [
            InlineKeyboardButton("📊 Статистика", callback_data="common_stats"),
            InlineKeyboardButton("🏆 Таблица лидеров", callback_data="common_leaderboard")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        achievements_text,
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