from sc2.bot_ai import BotAI

from .mixins import UnitReferenceMixin


class Enemy(UnitReferenceMixin):
    def __init__(self, bot: BotAI):
        self.bot: BotAI = bot
        # probably need to refresh this
        self.enemies_in_view = []
