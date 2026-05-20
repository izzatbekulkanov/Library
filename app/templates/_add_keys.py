import json

locales_dir = r"i:\Github\Library\app\locales"

new_keys = {
    "Tizimdagi barcha kutubxonalar ro'yxati va holati": {
        "uz": "Tizimdagi barcha kutubxonalar ro'yxati va holati",
        "ru": "Список и статус всех библиотек в системе",
        "en": "List and status of all libraries in the system"
    },
    "Kutubxonalardan qidirish...": {
        "uz": "Kutubxonalardan qidirish...",
        "ru": "Поиск по библиотекам...",
        "en": "Search libraries..."
    },
    "Yangi Kutubxona": {
        "uz": "Yangi Kutubxona",
        "ru": "Новая Библиотека",
        "en": "New Library"
    },
    "Manzili / Kontakt": {
        "uz": "Manzili / Kontakt",
        "ru": "Адрес / Контакт",
        "en": "Address / Contact"
    },
    "T/r": {
        "uz": "T/r",
        "ru": "№",
        "en": "No."
    },
    "Raqami:": {
        "uz": "Raqami:",
        "ru": "Номер:",
        "en": "Number:"
    },
    "Hozircha kutubxonalar mavjud emas": {
        "uz": "Hozircha kutubxonalar mavjud emas",
        "ru": "Библиотеки пока отсутствуют",
        "en": "No libraries available yet"
    },
    "ta kutubxona": {
        "uz": "ta kutubxona",
        "ru": "библиотек",
        "en": "libraries"
    },
    "Yangi Kutubxona Qo'shish": {
        "uz": "Yangi Kutubxona Qo'shish",
        "ru": "Добавить новую библиотеку",
        "en": "Add New Library"
    },
    "Kutubxonani Tahrirlash": {
        "uz": "Kutubxonani Tahrirlash",
        "ru": "Редактировать библиотеку",
        "en": "Edit Library"
    },
    "Yangi qo'shish": {
        "uz": "Yangi qo'shish",
        "ru": "Добавить новую",
        "en": "Add new"
    },
    "Kutubxona ma'lumotlarini kiriting": {
        "uz": "Kutubxona ma'lumotlarini kiriting",
        "ru": "Введите данные библиотеки",
        "en": "Enter library information"
    },
    "Kutubxona Nomi": {
        "uz": "Kutubxona Nomi",
        "ru": "Название библиотеки",
        "en": "Library Name"
    },
    "Kutubxona Raqami (ID)": {
        "uz": "Kutubxona Raqami (ID)",
        "ru": "Номер библиотеки (ID)",
        "en": "Library Number (ID)"
    },
    "Telefon Raqami (Ixtiyoriy)": {
        "uz": "Telefon Raqami (Ixtiyoriy)",
        "ru": "Номер телефона (необязательно)",
        "en": "Phone Number (Optional)"
    },
    "Manzili": {
        "uz": "Manzili",
        "ru": "Адрес",
        "en": "Address"
    },
    "Email Manzili (Ixtiyoriy)": {
        "uz": "Email Manzili (Ixtiyoriy)",
        "ru": "Email адрес (необязательно)",
        "en": "Email Address (Optional)"
    },
    "Faol holat (Active)": {
        "uz": "Faol holat (Active)",
        "ru": "Активный статус",
        "en": "Active Status"
    },
    "Holat faol qilinmasa foydalanuvchilar tanlay olmaydi": {
        "uz": "Holat faol qilinmasa foydalanuvchilar tanlay olmaydi",
        "ru": "Если статус неактивен, пользователи не смогут выбрать",
        "en": "If inactive, users cannot select this library"
    },
    "Kitob Klassifikatsiyasi": {
        "uz": "Kitob Klassifikatsiyasi",
        "ru": "Классификация книг",
        "en": "Book Classification"
    },
    "Tizimdagi barcha kitob turlari va BBK kategoriyalari": {
        "uz": "Tizimdagi barcha kitob turlari va BBK kategoriyalari",
        "ru": "Все типы книг и категории ББК в системе",
        "en": "All book types and BBK categories in the system"
    },
    "Qidirish...": {
        "uz": "Qidirish...",
        "ru": "Поиск...",
        "en": "Search..."
    },
    "Yangi Tur": {
        "uz": "Yangi Tur",
        "ru": "Новый тип",
        "en": "New Type"
    },
    "Yangi BBK": {
        "uz": "Yangi BBK",
        "ru": "Новый ББК",
        "en": "New BBK"
    },
    "Kitob Turlari": {
        "uz": "Kitob Turlari",
        "ru": "Типы книг",
        "en": "Book Types"
    },
    "BBK Kategoriyalari": {
        "uz": "BBK Kategoriyalari",
        "ru": "Категории ББК",
        "en": "BBK Categories"
    },
    "Muqova": {
        "uz": "Muqova",
        "ru": "Обложка",
        "en": "Cover"
    },
    "Kitob turlari topilmadi": {
        "uz": "Kitob turlari topilmadi",
        "ru": "Типы книг не найдены",
        "en": "No book types found"
    },
    "ta tur": {
        "uz": "ta tur",
        "ru": "типов",
        "en": "types"
    },
    "Kodi": {
        "uz": "Kodi",
        "ru": "Код",
        "en": "Code"
    },
    "BBK kategoriyalari topilmadi": {
        "uz": "BBK kategoriyalari topilmadi",
        "ru": "Категории ББК не найдены",
        "en": "No BBK categories found"
    },
    "ta kategoriya": {
        "uz": "ta kategoriya",
        "ru": "категорий",
        "en": "categories"
    },
    "Kitob turi qo'shish": {
        "uz": "Kitob turi qo'shish",
        "ru": "Добавить тип книги",
        "en": "Add book type"
    },
    "Kitob turini tahrirlash": {
        "uz": "Kitob turini tahrirlash",
        "ru": "Редактировать тип книги",
        "en": "Edit book type"
    },
    "Yangi kitob turi": {
        "uz": "Yangi kitob turi",
        "ru": "Новый тип книги",
        "en": "New book type"
    },
    "BBK qo'shish": {
        "uz": "BBK qo'shish",
        "ru": "Добавить ББК",
        "en": "Add BBK"
    },
    "BBK tahrirlash": {
        "uz": "BBK tahrirlash",
        "ru": "Редактировать ББК",
        "en": "Edit BBK"
    },
    "Yangi BBK kategoriyasi": {
        "uz": "Yangi BBK kategoriyasi",
        "ru": "Новая категория ББК",
        "en": "New BBK category"
    },
    "BBK Kodi": {
        "uz": "BBK Kodi",
        "ru": "Код ББК",
        "en": "BBK Code"
    },
    "Rasm yuklash (Ixtiyoriy)": {
        "uz": "Rasm yuklash (Ixtiyoriy)",
        "ru": "Загрузить изображение (необязательно)",
        "en": "Upload image (Optional)"
    },
    "Qurilmadan rasm tanlash": {
        "uz": "Qurilmadan rasm tanlash",
        "ru": "Выбрать изображение с устройства",
        "en": "Select image from device"
    },
    "Tizimda faol": {
        "uz": "Tizimda faol",
        "ru": "Активен в системе",
        "en": "Active in system"
    },
    "Yangi Kitob Qo'shish": {
        "uz": "Yangi Kitob Qo'shish",
        "ru": "Добавить новую книгу",
        "en": "Add New Book"
    },
    "Bosma kitob ma'lumotlarini kiriting": {
        "uz": "Bosma kitob ma'lumotlarini kiriting",
        "ru": "Введите данные печатной книги",
        "en": "Enter printed book information"
    },
    "Orqaga": {
        "uz": "Orqaga",
        "ru": "Назад",
        "en": "Back"
    },
