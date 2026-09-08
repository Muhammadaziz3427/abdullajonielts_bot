# Makhmudov Abdullajon Telegram Bot

Python va aiogram 3.x asosidagi ta'lim bot: kanalga majburiy obunani tekshiradi,
dars fayllarini Telegram `file_id` orqali beradi va barcha metama'lumotlarni JSON
fayllarda saqlaydi.

## Ishga tushirish

- `pip install -r requirements.txt` — Python bog'liqliklarini o'rnatish
- `python bot.py` — botni ishga tushirish
- Replit Run tugmasi `.replit` dagi `python bot.py` buyrug'idan foydalanadi

## Kerakli sozlamalar

- `BOT_TOKEN` — BotFather bergan token
- `ADMIN_ID` — Telegram admin foydalanuvchisining raqamli ID si
- `CHANNEL_ID` — ixtiyoriy boshlang'ich kanal username yoki ID si

`BOT_TOKEN` va `ADMIN_ID` ni Replit Secrets/environment variables bo'limida
saqlash kerak. Majburiy kanal keyinchalik Telegram ichidagi `/admin` paneldan
ham o'zgartiriladi. Obunani tekshirish uchun bot kanalga admin qilib qo'yilishi
kerak.

## Tuzilma

- `bot.py` — polling va routerlarni ishga tushiradi
- `config.py` — token, admin ID va fayl yo'llari
- `handlers/user.py` — `/start`, `/darslar`, obuna va dars yuborish
- `handlers/admin.py` — dars, foydalanuvchi va kanal boshqaruvi
- `utils/file_manager.py` — atomik JSON o'qish/yozish
- `utils/subscription.py` — Telegram kanal a'zoligini tekshirish
- `data/` — users, lessons va settings JSON fayllari

## Muhim qarorlar

- Video va PDF fayllar serverga yuklanmaydi: Telegram yuborgan `file_id`
  `lessons.json` ichida saqlanadi.
- Foydalanuvchi `/start`, `/darslar` yoki dars tugmasidan foydalanishda obunasi
  qayta tekshiriladi; obuna bekor qilinsa, darslar yopiladi.
