from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 Suggest Manga", callback_data="suggest_manga")
        ],
        [
            InlineKeyboardButton("📚 Library", callback_data="latest"),
            InlineKeyboardButton("🔍 Genres", callback_data="genres")
        ],
        [
            InlineKeyboardButton("🎲 Random", callback_data="random"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ]
    ])

def get_manga_list_keyboard(manga_list, prefix="manga"):
    buttons = []
    for m in manga_list:
        title = m['title']
        buttons.append([InlineKeyboardButton(title, callback_data=f"{prefix}:{m['manga_id']}")])
    
    # Back button to main menu
    buttons.append([InlineKeyboardButton("🔙 Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def get_genres_keyboard(genres):
    buttons = []
    row = []
    for i, genre in enumerate(genres):
        row.append(InlineKeyboardButton(genre, callback_data=f"genre:{genre}"))
        if len(row) == 2 or i == len(genres) - 1:
            buttons.append(row)
            row = []
            
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def get_chapters_keyboard(manga_id, chapters):
    buttons = []
    row = []
    for i, c in enumerate(chapters):
        row.append(InlineKeyboardButton(f"Ch. {c['chapter_number']}", callback_data=f"dl:{c['manga_id']}:{c['chapter_number']}"))
        if len(row) == 3 or i == len(chapters) - 1:
            buttons.append(row)
            row = []
            
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)
