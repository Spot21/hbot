import json
import random
import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import Question, TestResult, User, Topic, Achievement
from database.db_manager import get_session
from utils.formatters import format_question_text
from services.stats_service import update_user_stats
from utils.image_utils import get_image_path

logger = logging.getLogger(__name__)

class QuizService:
    def __init__(self):
        self.active_quizzes = {}  # словарь активных тестов: {user_id: quiz_data}

    def save_active_quizzes(self):
        """Сохранить состояние активных тестов"""
        with get_session() as session:
            for user_id, quiz_data in self.active_quizzes.items():
                # Здесь код для сохранения в БД или файл
                pass

    def restore_active_quizzes(self):
        """Восстановить активные тесты из БД"""
        with get_session() as session:
            # Здесь код для восстановления из БД или файла
            pass


    def get_topics(self) -> List[Dict[str, Any]]:
        """Получение списка всех доступных тем для тестирования"""
        with get_session() as session:
            topics = session.query(Topic).all()
            return [{"id": t.id, "name": t.name, "description": t.description} for t in topics]

    def start_quiz(self, user_id: int, topic_id: int, question_count: int = 10) -> Dict[str, Any]:
        """Начать новый тест для пользователя"""
        with get_session() as session:
            # Получаем вопросы для выбранной темы
            questions = (
                session.query(Question)
                .filter(Question.topic_id == topic_id)
                .order_by(Question.id)
                .all()
            )

            if not questions:
                return {"success": False, "message": "Нет доступных вопросов для выбранной темы"}

            # Выбираем случайные вопросы
            selected_questions = random.sample(questions, min(question_count, len(questions)))

            # Создаём структуру теста
            quiz_data = {
                "topic_id": topic_id,
                "questions": [
                    {
                        "id": q.id,
                        "text": q.text,
                        "options": json.loads(q.options),
                        "correct_answer": json.loads(q.correct_answer),
                        "question_type": q.question_type,
                        "explanation": q.explanation,
                        "media_url": q.media_url
                    }
                    for q in selected_questions
                ],
                "current_question": 0,
                "answers": {},
                "start_time": datetime.now(),
                "is_completed": False
            }

            # Сохраняем тест в активных
            self.active_quizzes[user_id] = quiz_data

            return {"success": True, "quiz_data": quiz_data}

    def get_current_question(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение текущего вопроса в тесте"""
        if user_id not in self.active_quizzes:
            return None

        quiz_data = self.active_quizzes[user_id]
        if quiz_data["current_question"] >= len(quiz_data["questions"]):
            return None

        question = quiz_data["questions"][quiz_data["current_question"]]
        return question

    def format_question_message(self, question: Dict[str, Any], question_num: int, total_questions: int,
                                user_id: int = None) -> Tuple[str, InlineKeyboardMarkup, Optional[str]]:
        """Форматирование вопроса для отправки в сообщении"""
        # Формируем текст вопроса
        question_text = f"*Вопрос {question_num}/{total_questions}*\n\n{question['text']}"

        # Добавляем информацию о типе вопроса
        if question["question_type"] == "multiple":
            question_text += "\n\n_Выберите все правильные варианты ответов_"
        elif question["question_type"] == "sequence":
            question_text += "\n\n_Расположите варианты в правильном порядке_"

        # Формируем клавиатуру с вариантами ответов
        keyboard = []
        if question["question_type"] == "single" or question["question_type"] == "multiple":
            # Для одиночного или множественного выбора
            for i, option in enumerate(question["options"]):
                button_text = option
                if question["question_type"] == "multiple" and user_id is not None:
                    # Для множественного выбора добавляем чекбоксы
                    selected = self.is_option_selected(user_id, question["id"], i)
                    button_text = f"{'☑' if selected else '☐'} {option}"
                callback_data = f"quiz_answer_{question['id']}_{i}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

            # Добавляем кнопку подтверждения для множественного выбора
            if question["question_type"] == "multiple":
                keyboard.append(
                    [InlineKeyboardButton("✅ Подтвердить выбор", callback_data=f"quiz_confirm_{question['id']}")])

        elif question["question_type"] == "sequence" and user_id is not None:
            # Для вопроса с последовательностью
            current_sequence = self.get_current_sequence(user_id, question["id"])
            if not current_sequence:
                # Показываем все варианты для выбора
                for i, option in enumerate(question["options"]):
                    keyboard.append(
                        [InlineKeyboardButton(f"{i + 1}. {option}", callback_data=f"quiz_seq_{question['id']}_{i}")])
            else:
                # Показываем текущую последовательность и оставшиеся варианты
                sequence_text = "\n".join(
                    [f"{i + 1}. {question['options'][int(opt)]}" for i, opt in enumerate(current_sequence)])
                question_text += f"\n\nТекущая последовательность:\n{sequence_text}"

                remaining_options = [i for i in range(len(question["options"])) if str(i) not in current_sequence]
                for i in remaining_options:
                    keyboard.append(
                        [InlineKeyboardButton(question["options"][i], callback_data=f"quiz_seq_{question['id']}_{i}")])

                # Добавляем кнопки сброса и подтверждения
                keyboard.append([
                    InlineKeyboardButton("🔄 Сбросить", callback_data=f"quiz_reset_{question['id']}"),
                    InlineKeyboardButton("✅ Подтвердить", callback_data=f"quiz_confirm_{question['id']}")
                ])
        elif question["question_type"] == "sequence" and user_id is None:
            # Для вопроса с последовательностью, если user_id не указан
            for i, option in enumerate(question["options"]):
                keyboard.append(
                    [InlineKeyboardButton(f"{i + 1}. {option}", callback_data=f"quiz_seq_{question['id']}_{i}")])

        # Добавляем кнопку пропуска
        keyboard.append([InlineKeyboardButton("⏩ Пропустить", callback_data="quiz_skip")])

        # Определяем медиа-файл, если есть
        media_file = None
        if question.get("media_url"):
            try:
                media_file = get_image_path(question["media_url"])
                # Проверка существования файла
                if not os.path.exists(media_file):
                    logger.warning(f"Media file not found: {media_file}")
                    media_file = None
            except Exception as e:
                logger.error(f"Error getting media file: {e}")
                media_file = None

        return question_text, InlineKeyboardMarkup(keyboard), media_file

    def is_option_selected(self, user_id: int, question_id: int, option_index: int) -> bool:
        """Проверка, выбран ли вариант ответа в вопросе с множественным выбором"""
        quiz_data = self.active_quizzes.get(user_id, {})
        answers = quiz_data.get("answers", {})
        question_answers = answers.get(str(question_id), [])
        return option_index in question_answers

    def get_current_sequence(self, user_id: int, question_id: int) -> List[str]:
        """Получение текущей последовательности для вопроса с сортировкой"""
        quiz_data = self.active_quizzes.get(user_id, {})
        answers = quiz_data.get("answers", {})
        return answers.get(str(question_id), [])

    def submit_answer(self, user_id: int, question_id: int, answer) -> Dict[str, Any]:
        """Обработка ответа пользователя"""
        if user_id not in self.active_quizzes:
            return {"success": False, "message": "Нет активного теста"}

        quiz_data = self.active_quizzes[user_id]
        question_index = quiz_data["current_question"]

        if question_index >= len(quiz_data["questions"]):
            return {"success": False, "message": "Вопросы закончились"}

        current_question = quiz_data["questions"][question_index]

        # Сохраняем ответ
        quiz_data["answers"][str(current_question["id"])] = answer

        # Переходим к следующему вопросу
        quiz_data["current_question"] += 1

        # Проверяем, закончился ли тест
        if quiz_data["current_question"] >= len(quiz_data["questions"]):
            quiz_data["is_completed"] = True
            result = self.complete_quiz(user_id)
            return {"success": True, "is_completed": True, "result": result}

        return {"success": True, "is_completed": False}

    def skip_question(self, user_id: int) -> Dict[str, Any]:
        """Пропуск текущего вопроса"""
        if user_id not in self.active_quizzes:
            return {"success": False, "message": "Нет активного теста"}

        quiz_data = self.active_quizzes[user_id]
        question_index = quiz_data["current_question"]

        if question_index >= len(quiz_data["questions"]):
            return {"success": False, "message": "Вопросы закончились"}

        # Переходим к следующему вопросу
        quiz_data["current_question"] += 1

        # Проверяем, закончился ли тест
        if quiz_data["current_question"] >= len(quiz_data["questions"]):
            quiz_data["is_completed"] = True
            result = self.complete_quiz(user_id)
            return {"success": True, "is_completed": True, "result": result}

        return {"success": True, "is_completed": False}

    def complete_quiz(self, user_id: int) -> Dict[str, Any]:
        """Завершение теста и подсчет результатов"""
        if user_id not in self.active_quizzes:
            return {"success": False, "message": "Нет активного теста"}

        quiz_data = self.active_quizzes[user_id]
        answers = quiz_data["answers"]
        questions = quiz_data["questions"]

        # Подсчитываем результаты
        correct_count = 0
        total_questions = len(questions)
        question_results = []

        for question in questions:
            question_id = str(question["id"])
            user_answer = answers.get(question_id, None)
            is_correct = False

            if user_answer is not None:
                if question["question_type"] == "single":
                    is_correct = user_answer == question["correct_answer"][0]
                elif question["question_type"] == "multiple":
                    is_correct = set(user_answer) == set(question["correct_answer"])
                elif question["question_type"] == "sequence":
                    is_correct = user_answer == question["correct_answer"]

            question_results.append({
                "question": question["text"],
                "user_answer": user_answer,
                "correct_answer": question["correct_answer"],
                "is_correct": is_correct,
                "explanation": question.get("explanation", "")
            })

            if is_correct:
                correct_count += 1

        # Рассчитываем процент
        percentage = round((correct_count / total_questions) * 100, 1) if total_questions > 0 else 0

        # Сохраняем результаты в базу
        with get_session() as session:
            user = session.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return {"success": False, "message": "Пользователь не найден"}

            # Создаем запись о результатах теста
            test_result = TestResult(
                user_id=user.id,
                topic_id=quiz_data["topic_id"],
                score=correct_count,
                max_score=total_questions,
                percentage=percentage,
                time_spent=(datetime.now() - quiz_data["start_time"]).seconds
            )
            session.add(test_result)
            session.commit()

            # Обновляем статистику пользователя
            update_user_stats(user_id)

            # Проверяем достижения
            self.check_achievements(user_id, correct_count, total_questions, percentage)

        # Удаляем тест из активных
        del self.active_quizzes[user_id]

        return {
            "success": True,
            "correct_count": correct_count,
            "total_questions": total_questions,
            "percentage": percentage,
            "question_results": question_results
        }

    def check_achievements(self, user_id: int, correct_count: int, total_questions: int, percentage: float) -> List[
        Dict[str, Any]]:
        """Проверка и выдача достижений"""
        new_achievements = []

        with get_session() as session:
            user = session.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return []

            # Получаем уже имеющиеся достижения пользователя
            existing_achievements = {a.name for a in user.achievements}

            # Проверяем условия для разных достижений
            achievements_to_check = [
                # Достижения за прохождение тестов
                {"name": "Первый тест", "description": "Пройден первый тест!", "points": 10,
                 "condition": True, "badge_url": "badges/first_test.png"},
                {"name": "Отличник", "description": "Получите 100% в тесте", "points": 50,
                 "condition": percentage == 100, "badge_url": "badges/perfect_score.png"},
                {"name": "Знаток истории", "description": "Пройдите 10 тестов", "points": 100,
                 "condition": len(user.results) >= 10, "badge_url": "badges/history_expert.png"},
            ]

            # Проверяем каждое достижение
            for achievement_data in achievements_to_check:
                if (achievement_data["name"] not in existing_achievements and
                        achievement_data["condition"]):
                    # Создаем новое достижение
                    achievement = Achievement(
                        user_id=user.id,
                        name=achievement_data["name"],
                        description=achievement_data["description"],
                        badge_url=achievement_data.get("badge_url"),
                        points=achievement_data.get("points", 0)
                    )
                    session.add(achievement)
                    new_achievements.append(achievement_data)

            # Если есть новые достижения, фиксируем изменения
            if new_achievements:
                session.commit()

        return new_achievements