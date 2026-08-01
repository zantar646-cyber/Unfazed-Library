from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

main_reply = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Search Books"), KeyboardButton(text="Categories")],
        [KeyboardButton(text="Popular"), KeyboardButton(text="Recent")],
        [KeyboardButton(text="Favorites"), KeyboardButton(text="History")],
        [KeyboardButton(text="Help")],
    ],
    resize_keyboard=True,
)

remove_keyboard = ReplyKeyboardRemove()
