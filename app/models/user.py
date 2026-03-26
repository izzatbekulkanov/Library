from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Date, DateTime, Table, Enum
from sqlalchemy.orm import relationship
import enum
import bcrypt
from datetime import datetime
from app.core.database import Base

# Asosiy Many-to-Many uzatish (association) jadvallari

user_roles_association = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("role_id", Integer, ForeignKey("roles.id")),
    extend_existing=True
)

class GenderEnum(str, enum.Enum):
    male = "Erkak"
    female = "Ayol"

class UserTypeEnum(str, enum.Enum):
    user = "Foydalanuvchi"
    admin = "Administrator"
    lib_staff = "Kutubxona xodimi"
    lib_head = "Kutubxona Raxbari"
    guest = "Mehmon"


class Roles(Base):
    __tablename__ = "roles"
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, index=True)
    name = Column(String(255))
    
    # M2M bog'lanish
    users = relationship("User", secondary=user_roles_association, back_populates="hemis_role")


class User(Base):
    __tablename__ = "users"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    
    # Shaxsiy Ma'lumotlar
    full_name = Column(String(255), nullable=True)
    short_name = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    second_name = Column(String(255), nullable=True)
    third_name = Column(String(255), nullable=True)
    gender = Column(Enum(GenderEnum), nullable=True)
    birth_date = Column(Date, nullable=True)
    image = Column(String(255), nullable=True)
    imageFile = Column(String(255), nullable=True) # default as string url here
    
    # Tahsil / Yosh / Aloqa
    year_of_enter = Column(String(255), nullable=True)
    age = Column(Integer, nullable=True)
    phone_number = Column(String(15), nullable=True)
    
    # Hisob qaydnomasi bazaviy malumotlari
    username = Column(String(255), unique=True, index=True, nullable=True)
    email = Column(String(255), unique=True, index=True)
    hashed_password = Column(String(255))
    password_save = Column(String(128), nullable=True)
    user_type = Column(Enum(UserTypeEnum), default=UserTypeEnum.user)
    
    # Holat va vaqt
    is_followers_book = Column(Boolean, default=False)
    last_login = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_staff = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    # Sidebar/menu bo'limlari uchun ruxsatlar (vergul bilan: dashboard,books,...)
    menu_permissions = Column(String(1024), nullable=True)
    
    # Qo'shimcha
    hemis_id = Column(String(255), nullable=True)
    telegram = Column(String(255), nullable=True)
    instagram = Column(String(255), nullable=True)
    facebook = Column(String(255), nullable=True)

    # Aloqalar (Relationships)
    hemis_role = relationship("Roles", secondary=user_roles_association, back_populates="users")

    def verify_password(self, plain_password):
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            self.hashed_password.encode("utf-8")
        )

    @staticmethod
    def get_password_hash(password: str) -> str:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
