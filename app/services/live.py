import time as _time

from ._common import *
from .game_data import Log


LIVE_STATUS_PATH = os.path.join(ROOT_DIR, "data/persist/live.json")

# Idle payload served by GET /persist/static/live. ``now`` is always injected
# with the current server time; every other field is admin-editable through the
# Maintenance page and read fresh on each request so changes apply on the next
# client poll (``poll`` seconds).
DEFAULT_LIVE_STATUS = {
    "maintenance": None,
    "maint_ended": 0,
    "notices": [],
    "poll": 60,
    "flags": {"GoogleRestore": {"on": False}},
    "texts": {
        "maint_soon": {
            "EN": "Short maintenance in {min} min.\n\nYour progress is saved - finish your battle and you'll be fine.",
            "ES": "Mantenimiento breve en {min} min.\n\nTu progreso está guardado: termina tu batalla sin problema.",
            "FR": "Courte maintenance dans {min} min.\n\nTa progression est sauvegardée : termine ton combat sans souci.",
            "IT": "Breve manutenzione tra {min} min.\n\nI tuoi progressi sono salvati: finisci pure la battaglia.",
            "PT": "Manutenção breve em {min} min.\n\nSeu progresso está salvo: termine sua batalha sem problemas.",
            "TR": "{min} dakika içinde kısa bir bakım var.\n\nİlerlemen kaydedildi, savaşını rahatça bitirebilirsin.",
            "AR": "صيانة قصيرة بعد {min} دقيقة.\n\nتم حفظ تقدمك، أكمل معركتك بلا قلق.",
            "VI": "Bảo trì ngắn sau {min} phút.\n\nTiến trình của bạn đã được lưu, cứ hoàn thành trận đấu nhé.",
        },
        "content_new": {
            "EN": "New content is available!\n\nRestart the game to get it.",
            "ES": "¡Hay contenido nuevo!\n\nReinicia el juego para obtenerlo.",
            "FR": "Du nouveau contenu est disponible !\n\nRedémarre le jeu pour l'obtenir.",
            "IT": "Sono disponibili nuovi contenuti!\n\nRiavvia il gioco per ottenerli.",
            "PT": "Novo conteúdo disponível!\n\nReinicie o jogo para obtê-lo.",
            "TR": "Yeni içerik var!\n\nAlmak için oyunu yeniden başlat.",
            "AR": "يتوفر محتوى جديد!\n\nأعد تشغيل اللعبة للحصول عليه.",
            "VI": "Đã có nội dung mới!\n\nHãy khởi động lại trò chơi để nhận.",
        },
        "feature_off": {
            "EN": "This is closed for a short while. Please try again later.",
            "ES": "Esto está cerrado por un momento. Inténtalo más tarde.",
            "FR": "Ceci est fermé pour un petit moment. Réessaie plus tard.",
            "IT": "Questa funzione è chiusa per poco. Riprova più tardi.",
            "PT": "Isto está fechado por um tempo. Tente novamente mais tarde.",
            "TR": "Bu kısa bir süreliğine kapalı. Lütfen daha sonra tekrar dene.",
            "AR": "هذا مغلق لفترة قصيرة. يرجى المحاولة لاحقاً.",
            "VI": "Mục này tạm đóng một lúc. Vui lòng thử lại sau.",
        },
        "restart_soon": {
            "EN": "The game will restart in {min} min to load new content.\n\nFinish your battle - your progress is saved.",
            "ES": "El juego se reiniciará en {min} min para cargar contenido nuevo.\n\nTermina tu batalla: tu progreso está guardado.",
            "FR": "Le jeu va redémarrer dans {min} min pour charger du nouveau contenu.\n\nTermine ton combat : ta progression est sauvegardée.",
            "IT": "Il gioco si riavvierà tra {min} min per caricare nuovi contenuti.\n\nFinisci la battaglia: i tuoi progressi sono salvati.",
            "PT": "O jogo vai reiniciar em {min} min para carregar conteúdo novo.\n\nTermine sua batalha: seu progresso está salvo.",
            "TR": "Oyun yeni içeriği yüklemek için {min} dakika içinde yeniden başlayacak.\n\nSavaşını bitir, ilerlemen kaydedildi.",
            "AR": "ستعيد اللعبة التشغيل بعد {min} دقيقة لتحميل محتوى جديد.\n\nأكمل معركتك، تم حفظ تقدمك.",
            "VI": "Trò chơi sẽ khởi động lại sau {min} phút để tải nội dung mới.\n\nHãy hoàn thành trận đấu, tiến trình đã được lưu.",
        },
        "restart_now": {
            "EN": "Restarting the game to load new content.\n\nYour progress is saved.",
            "ES": "Reiniciando el juego para cargar contenido nuevo.\n\nTu progreso está guardado.",
            "FR": "Redémarrage du jeu pour charger du nouveau contenu.\n\nTa progression est sauvegardée.",
            "IT": "Riavvio del gioco per caricare nuovi contenuti.\n\nI tuoi progressi sono salvati.",
            "PT": "Reiniciando o jogo para carregar conteúdo novo.\n\nSeu progresso está salvo.",
            "TR": "Yeni içeriği yüklemek için oyun yeniden başlatılıyor.\n\nİlerlemen kaydedildi.",
            "AR": "جارٍ إعادة تشغيل اللعبة لتحميل محتوى جديد.\n\nتم حفظ تقدمك.",
            "VI": "Đang khởi động lại trò chơi để tải nội dung mới.\n\nTiến trình của bạn đã được lưu.",
        },
        "save_unreadable": {
            "EN": "Your progress could not be loaded on this version of the game.\n\nIt is safe on the server - please update the game.",
            "ES": "No se pudo cargar tu progreso en esta versión del juego.\n\nEstá a salvo en el servidor: actualiza el juego.",
            "FR": "Ta progression n'a pas pu être chargée sur cette version du jeu.\n\nElle est en sécurité sur le serveur : mets le jeu à jour.",
            "IT": "Non è stato possibile caricare i tuoi progressi su questa versione del gioco.\n\nSono al sicuro sul server: aggiorna il gioco.",
            "PT": "Não foi possível carregar seu progresso nesta versão do jogo.\n\nEle está seguro no servidor: atualize o jogo.",
            "TR": "İlerlemen oyunun bu sürümünde yüklenemedi.\n\nSunucuda güvende, lütfen oyunu güncelle.",
            "AR": "تعذر تحميل تقدمك في هذا الإصدار من اللعبة.\n\nتقدمك آمن على الخادم، يرجى تحديث اللعبة.",
            "VI": "Không thể tải tiến trình của bạn trên phiên bản trò chơi này.\n\nTiến trình vẫn an toàn trên máy chủ, hãy cập nhật trò chơi.",
        },
    },
    "content": "0390f66a81ab21a3f6c7f8a076543193",
    "ui": [],
    "restart": None,
}


def LoadLiveStatus():
    """Read ``data/persist/live.json`` merged over the defaults."""
    status = copy.deepcopy(DEFAULT_LIVE_STATUS)
    if os.path.exists(LIVE_STATUS_PATH):
        try:
            with open(LIVE_STATUS_PATH, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                status.update(stored)
        except (OSError, ValueError) as e:
            Log("live", f"Failed to load live.json: {e}")
    return status


def SaveLiveStatus(data):
    """Persist the live status config (rejects non-dict values)."""
    if not isinstance(data, dict):
        raise ValueError("Live status must be a JSON object")
    os.makedirs(os.path.dirname(LIVE_STATUS_PATH), exist_ok=True)
    with open(LIVE_STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def GetLiveStatus():
    """Return the live status payload with a fresh ``now`` timestamp."""
    status = LoadLiveStatus()
    status["now"] = int(_time.time())
    return status
