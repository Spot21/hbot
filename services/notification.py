import logging
import asyncio
import json
import traceback
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from database.models import User, Notification
from database.db_manager import get_session
from services.parent_service import ParentService

logger = logging.getLogger(__name__)


class NotificationService:
    """Сервис для отправки уведомлений пользователям"""

    def __init__(self, application: Application):
        """Инициализация сервиса уведомлений"""
        self.application = application
        self.scheduler = None
        self._running = False
        self.parent_service = ParentService()

    async def start(self):
        """Запуск планировщика уведомлений"""
        try:
            if self._running:
                logger.warning("Notification service is already running")
                return

            # Создаем планировщик
            self.scheduler = AsyncIOScheduler()

            # Добавляем задачи с использованием асинхронных функций
            self.scheduler.add_job(
                self.process_notifications,
                'interval',
                minutes=5,
                id='process_notifications'
            )
            self.scheduler.add_job(
                self.send_weekly_reports,
                'cron',
                day_of_week='sun',
                hour=10,
                id='send_weekly_reports'
            )
            self.scheduler.add_job(
                self.send_reminders,
                'cron',
                hour=18,
                id='send_reminders'
            )

            # Запускаем планировщик
            self.scheduler.start()
            self._running = True
            logger.info("Notification scheduler started")
        except Exception as e:
            logger.error(f"Error starting notification scheduler: {e}")
            logger.error(traceback.format_exc())
            self._running = False

    async def stop(self):
        """Остановка планировщика уведомлений"""
        try:
            if self.scheduler and self._running:
                self.scheduler.shutdown(wait=True)  # Изменено на wait=True для более безопасного завершения
                self._running = False
                logger.info("Notification scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping notification scheduler: {e}")
            logger.error(traceback.format_exc())

    async def process_notifications(self):
        """Обработка и отправка запланированных уведомлений"""
        if not self._running:
            return

        try:
            with get_session() as session:
                # Получаем все непрочитанные уведомления
                notifications = session.query(Notification).filter(
                    Notification.is_read == False,
                    Notification.scheduled_at <= datetime.utcnow()
                ).all()

                for notification in notifications:
                    # Получаем пользователя
                    user = session.query(User).get(notification.user_id)
                    if not user:
                        logger.warning(f"User not found for notification {notification.id}")
                        notification.is_read = True
                        continue

                    # Отправляем уведомление
                    try:
                        await self.application.bot.send_message(
                            chat_id=user.telegram_id,
                            text=f"*{notification.title}*\n\n{notification.message}",
                            parse_mode="Markdown"
                        )

                        # Помечаем уведомление как прочитанное
                        notification.is_read = True
                        logger.info(f"Notification {notification.id} sent to user {user.telegram_id}")

                    except Exception as e:
                        logger.error(f"Error sending notification {notification.id} to user {user.telegram_id}: {e}")
                        logger.error(traceback.format_exc())

                # Сохраняем изменения
                session.commit()

        except Exception as e:
            logger.error(f"Error processing notifications: {e}")
            logger.error(traceback.format_exc())

    async def send_weekly_reports(self):
        """Отправка еженедельных отчетов родителям"""
        if not self._running:
            return

        try:
            logger.info("Starting weekly reports generation in NotificationService")
            await self.parent_service.send_weekly_reports()
            logger.info("Weekly reports generation completed in NotificationService")
        except Exception as e:
            logger.error(f"Error sending weekly reports: {e}")
            logger.error(traceback.format_exc())

    async def send_reminders(self):
        """Отправка напоминаний о необходимости пройти тест"""
        if not self._running:
            return

        try:
            with get_session() as session:
                # Получаем всех учеников, которые не проходили тест более недели
                week_ago = datetime.utcnow() - timedelta(days=7)
                inactive_students = session.query(User).filter(
                    User.role == "student",
                    User.last_active < week_ago
                ).all()

                for student in inactive_students:
                    try:
                        await self.application.bot.send_message(
                            chat_id=student.telegram_id,
                            text="👋 Привет! Не забывай регулярно проверять свои знания по истории.\n"
                                 "Используй команду /test, чтобы начать тестирование."
                        )
                        logger.info(f"Reminder sent to student {student.telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending reminder to student {student.telegram_id}: {e}")
                        logger.error(traceback.format_exc())

        except Exception as e:
            logger.error(f"Error sending reminders: {e}")
            logger.error(traceback.format_exc())

    async def create_notification(self, user_id: int, title: str, message: str,
                                  notification_type: str, scheduled_at: datetime = None) -> bool:
        """Создание нового уведомления"""
        try:
            with get_session() as session:
                # Проверяем существование пользователя
                user = session.query(User).get(user_id)
                if not user:
                    return False

                # Создаем уведомление
                notification = Notification(
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    scheduled_at=scheduled_at
                )
                session.add(notification)
                session.commit()

                # Если уведомление нужно отправить сейчас, запускаем обработку
                if scheduled_at is None or scheduled_at <= datetime.utcnow():
                    await self.process_notifications()

                return True

        except Exception as e:
            logger.error(f"Error creating notification: {e}")
            return False

    async def notify_test_completion(self, student_id: int, test_result: dict) -> None:
        """Уведомление родителей о завершении теста учеником"""
        try:
            # Получаем данные ученика
            with get_session() as session:
                student = session.query(User).get(student_id)
                if not student or student.role != "student":
                    return

                # Находим родителей этого ученика
                parents_query = (
                    session.query(User)
                    .filter(User.role == "parent")
                    .filter(User.children.any(id=student_id))
                )
                parents = parents_query.all()

                if not parents:
                    return

                # Определяем результат теста для сообщения
                percentage = test_result.get("percentage", 0)
                correct_count = test_result.get("correct_count", 0)
                total_questions = test_result.get("total_questions", 0)

                # Формируем текст уведомления
                if percentage >= 90:
                    result_description = "отличный результат"
                elif percentage >= 70:
                    result_description = "хороший результат"
                elif percentage >= 50:
                    result_description = "удовлетворительный результат"
                else:
                    result_description = "требуется дополнительная работа над материалом"

                message = (
                    f"Ученик {student.full_name or student.username} завершил тестирование.\n\n"
                    f"Результат: {correct_count} из {total_questions} правильных ответов ({percentage}%).\n"
                    f"Оценка: {result_description}.\n\n"
                    f"Для просмотра подробного отчета используйте команду /report."
                )

                # Для каждого родителя проверяем настройки уведомлений
                for parent in parents:
                    if not parent.settings:
                        continue

                    settings = json.loads(parent.settings)

                    if "student_notifications" not in settings:
                        continue

                    student_settings = settings["student_notifications"].get(str(student_id), {})

                    # Проверяем, нужно ли отправлять уведомление о завершении теста
                    if not student_settings.get("test_completion", False):
                        continue

                    # Проверяем пороговые значения результатов
                    low_threshold = student_settings.get("low_score_threshold", 60)
                    high_threshold = student_settings.get("high_score_threshold", 90)

                    send_notification = False

                    if percentage < low_threshold:
                        send_notification = True
                        title = "Низкий результат теста"
                    elif percentage >= high_threshold:
                        send_notification = True
                        title = "Высокий результат теста"

                    if send_notification:
                        # Создаем уведомление для родителя
                        notification = Notification(
                            user_id=parent.id,
                            title=title,
                            message=message,
                            notification_type="test_result"
                        )
                        session.add(notification)

                # Сохраняем изменения
                session.commit()

        except Exception as e:
            logger.error(f"Error notifying about test completion: {e}")
