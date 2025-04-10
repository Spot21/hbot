import logging
import os
import traceback
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from config import DB_ENGINE, DATA_DIR
from database.models import Base

# Настройка логирования
logger = logging.getLogger(__name__)

# Создаем директорию для базы данных, если она не существует
os.makedirs(os.path.dirname(DB_ENGINE.replace('sqlite:///', '')), exist_ok=True)

# Создаем движок базы данных с настройками для SQLite
if DB_ENGINE.startswith('sqlite:///'):
    engine = create_engine(
        DB_ENGINE,
        connect_args={"check_same_thread": False},  # Для SQLite
        echo=False  # Установите True для отладки SQL-запросов
    )
else:
    engine = create_engine(DB_ENGINE, echo=False)

# Создаем фабрику сессий
Session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))

def init_db():
    """Инициализация базы данных"""
    try:
        # Проверяем и создаем директорию для SQLite
        if DB_ENGINE.startswith('sqlite:///'):
            db_path = DB_ENGINE.replace('sqlite:///', '')
            db_dir = os.path.dirname(os.path.abspath(db_path))
            # Проверка прав на запись
            test_file = os.path.join(db_dir, 'test_write.tmp')
            try:
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                logger.info(f"Проверка прав на запись в директорию {db_dir} успешна")
            except Exception as e:
                logger.error(f"Ошибка при проверке прав на запись в директорию {db_dir}: {e}")

            logger.info(f"База данных SQLite будет создана по пути: {db_path}")
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            logger.info(f"База данных SQLite будет создана по пути: {db_path}")

        # Создаем все таблицы
        Base.metadata.create_all(engine)
        logger.info("Таблицы в базе данных созданы успешно")

        # Проверяем, есть ли уже данные в базе
        with get_session() as session:
            from database.models import User
            user_count = session.query(User).count()
            logger.info(f"Количество пользователей в базе: {user_count}")

            # Если база пуста, добавляем начальные данные
            if user_count == 0:
                add_default_data()
                logger.info("Начальные данные добавлены успешно")
            else:
                logger.info("База данных уже содержит данные, пропускаем добавление начальных данных")

    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        logger.error(traceback.format_exc())
        raise


@contextmanager
def get_session():
    """Контекстный менеджер для работы с сессией базы данных"""
    session = Session()
    try:
        logger.debug("Открыта новая сессия базы данных")
        yield session
        session.commit()
        logger.debug("Сессия успешно закрыта с commit")
    except Exception as e:
        session.rollback()
        logger.error(f"Ошибка в сессии базы данных, выполнен rollback: {e}")
        logger.error(traceback.format_exc())
        raise
    finally:
        session.close()
        logger.debug("Сессия закрыта в блоке finally")


def add_default_data():
    """Добавление начальных данных в базу данных"""
    from database.models import User, Topic

    try:
        with get_session() as session:
            # Проверяем, есть ли уже администратор
            admin_exists = session.query(User).filter(User.role == "admin").first() is not None

            if not admin_exists:
                # Добавляем администратора (ID нужно заменить на реальный)
                admin = User(
                    telegram_id=123456789,  # Замените на реальный ID
                    username="admin",
                    full_name="Admin",
                    role="admin"
                )
                session.add(admin)
                logger.info("Default admin user added")

            # Проверяем, есть ли уже темы
            topics_exist = session.query(Topic).first() is not None

            if not topics_exist:
                # Добавляем несколько начальных тем
                topics = [
                    Topic(name="Древняя Русь IX-XII вв.",
                          description="Вопросы по истории Древней Руси в период IX-XII веков"),
                    Topic(name="Русь в XIII-XV вв.", description="Вопросы по истории Руси в период XIII-XV веков"),
                    Topic(name="Россия в XVI-XVII вв.",
                          description="Вопросы по истории России в период XVI-XVII веков"),
                    Topic(name="Российская империя в XVIII в.",
                          description="Вопросы по истории Российской империи в XVIII веке"),
                    Topic(name="Российская империя в XIX - начале XX в.",
                          description="Вопросы по истории Российской империи в XIX - начале XX века"),
                    Topic(name="Революция и Гражданская война",
                          description="Вопросы по истории Революции и Гражданской войны"),
                    Topic(name="СССР в 1922-1941 гг.", description="Вопросы по истории СССР в межвоенный период"),
                    Topic(name="Великая Отечественная война",
                          description="Вопросы по истории Великой Отечественной войны"),
                    Topic(name="СССР в 1945-1991 гг.", description="Вопросы по истории СССР в послевоенный период"),
                    Topic(name="Российская Федерация", description="Вопросы по истории современной России")
                ]

                session.add_all(topics)
                logger.info("Default topics added")

            session.commit()
            logger.info("Default data added successfully")

    except Exception as e:
        logger.error(f"Error adding default data: {e}")
        raise