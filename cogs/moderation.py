import discord
from discord import Forbidden
from discord.ext import commands
from discord.http import Route

from utils import checks

MUTED_ROLE = "316134780976758786"


class Moderation:
    def __init__(self, bot):
        self.bot = bot
        self.no_ban_logs = set()

    @commands.command(hidden=True, pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def slowmode(self, ctx, timeout: int = 10):
        """Slows a channel."""
        try:
            await self.bot.http.request(Route('PATCH', '/channels/{channel_id}', channel_id=ctx.message.channel.id),
                                        json={"rate_limit_per_user": timeout})
            await self.bot.say(f"Ratelimit set to {timeout} seconds.")
        except:
            await self.bot.say("Failed to set ratelimit.")

    @commands.command(hidden=True, pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def purge_bot(self, ctx, limit: int = 50):
        """Purges bot messages from the last [limit] messages (default 50)."""
        deleted = await self.bot.purge_from(ctx.message.channel, check=lambda m: m.author.bot, limit=limit)
        await self.bot.say("Cleaned {} messages.".format(len(deleted)))

    @commands.command(hidden=True, pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def copyperms(self, ctx, role: discord.Role, source: discord.Channel, overwrite: bool = False):
        """Copies permission overrides for one role from one channel to all others of the same type."""
        source_chan = source
        source_role = role
        source_overrides = source_chan.overwrites_for(source_role)
        skipped = []
        for chan in ctx.message.server.channels:
            if chan.type != source_chan.type:
                continue
            chan_overrides = chan.overwrites_for(source_role)
            if chan_overrides.is_empty() or overwrite:
                await self.bot.edit_channel_permissions(chan, source_role, source_overrides)
            else:
                skipped.append(chan.name)

        if skipped:
            skipped_str = ', '.join(skipped)
            await self.bot.say(f":ok_hand:\n"
                               f"Skipped {skipped_str}; use `.copyperms {role} {source} true` to overwrite existing.")
        else:
            await self.bot.say(f":ok_hand:")

    @commands.command(hidden=True, pass_context=True, no_pm=True)
    @checks.mod_or_permissions(ban_members=True)
    async def raidmode(self, ctx, method='kick'):
        """Toggles raidmode in a server.
        Methods: kick, ban, lockdown"""
        if method not in ("kick", "ban", "lockdown"):
            return await self.bot.say("Raidmode method must be kick, ban, or lockdown.")

        server_settings = await self.get_server_settings(ctx.message.server.id, ['raidmode'])

        if server_settings['raidmode']:
            if server_settings['raidmode'] == 'lockdown':
                await self.end_lockdown(ctx)
            server_settings['raidmode'] = None
            out = "Raid mode disabled."
        else:
            if method == 'lockdown':
                await self.start_lockdown(ctx)
            server_settings['raidmode'] = method
            out = f"Raid mode enabled. Method: {method}"

        await self.set_server_settings(ctx.message.server.id, server_settings)
        await self.bot.say(out)

    @commands.command(hidden=True, pass_context=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def mute(self, ctx, target: discord.Member):
        """Mutes a member."""
        pass

    @commands.command(hidden=True, pass_context=True)
    @checks.mod_or_permissions(manage_roles=True)
    async def unmute(self, ctx, target: discord.Member):
        """Unmutes a member."""
        pass

    @commands.command(hidden=True, pass_context=True)
    @checks.mod_or_permissions(kick_members=True)
    async def kick(self, ctx, user: discord.Member, *, reason='Unknown reason'):
        """Kicks a member and logs it to #mod-log."""
        try:
            await self.bot.kick(user)
        except Forbidden:
            return await self.bot.say('Error: The bot does not have `kick_members` permission.')

        server_settings = await self.get_server_settings(ctx.message.server.id, ['cases', 'casenum'])

        case = Case.new(num=server_settings['casenum'], type_='kick', user=user.id, username=str(user), reason=reason,
                        mod=str(ctx.message.author))
        await self.post_action(ctx, server_settings, case)

    @commands.command(hidden=True, pass_context=True)
    @checks.mod_or_permissions(ban_members=True)
    async def ban(self, ctx, user: discord.Member, *, reason='Unknown reason'):
        """Bans a member and logs it to #mod-log."""
        try:
            self.no_ban_logs.add(ctx.message.server.id)
            await self.bot.ban(user)
        except Forbidden:
            return await self.bot.say('Error: The bot does not have `ban_members` permission.')
        finally:
            self.no_ban_logs.remove(ctx.message.server.id)

        server_settings = await self.get_server_settings(ctx.message.server.id, ['cases', 'casenum'])

        case = Case.new(num=server_settings['casenum'], type_='ban', user=user.id, username=str(user), reason=reason,
                        mod=str(ctx.message.author))
        await self.post_action(ctx, server_settings, case)

    @commands.command(hidden=True, pass_context=True)
    @checks.mod_or_permissions(ban_members=True)
    async def forceban(self, ctx, user, *, reason='Unknown reason'):
        """Force-bans a member ID and logs it to #mod-log."""
        member = discord.utils.get(ctx.message.server.members, id=user)
        if member:  # if they're still in the server, normal ban them
            return await ctx.invoke(self.ban, member, reason=reason)

        server_settings = await self.get_server_settings(ctx.message.server.id, ['cases', 'casenum', 'forcebanned'])
        server_settings['forcebanned'].append(user)

        case = Case.new(num=server_settings['casenum'], type_='forceban', user=user.id, username=str(user),
                        reason=reason, mod=str(ctx.message.author))
        await self.post_action(ctx, server_settings, case)

    @commands.command(hidden=True, pass_context=True)
    @checks.mod_or_permissions(ban_members=True)
    async def softban(self, ctx, user: discord.Member, *, reason='Unknown reason'):
        """Softbans a member and logs it to #mod-log."""
        try:
            self.no_ban_logs.add(ctx.message.server.id)
            await self.bot.ban(user)
            await self.bot.unban(ctx.message.server, user)
        except Forbidden:
            return await self.bot.say('Error: The bot does not have `ban_members` permission.')
        finally:
            self.no_ban_logs.remove(ctx.message.server.id)

        server_settings = await self.get_server_settings(ctx.message.server.id, ['cases', 'casenum'])

        case = Case.new(num=server_settings['casenum'], type_='softban', user=user.id, username=str(user),
                        reason=reason, mod=str(ctx.message.author))
        await self.post_action(ctx, server_settings, case)

    @commands.command(hidden=True, pass_context=True)
    @checks.mod_or_permissions(kick_members=True)
    async def reason(self, ctx, case_num: int, *, reason):
        """Sets the reason for a post in mod-log."""
        server_settings = await self.get_server_settings(ctx.message.server.id, ['cases'])
        cases = server_settings['cases']
        case = next((c for c in cases if c['num'] == case_num), None)
        if case is None:
            return await self.bot.say(f"Case {case_num} not found.")

        case = Case.from_dict(case)
        case.reason = reason
        case.mod = str(ctx.message.author)

        mod_log = discord.utils.get(ctx.message.server.channels, name='mod-log')
        if mod_log is not None and case.log_msg:
            log_message = await self.bot.get_message(mod_log, case.log_msg)
            await self.bot.edit_message(log_message, str(case))

        await self.set_server_settings(ctx.message.server.id, server_settings)
        await self.bot.say(':ok_hand:')

    async def post_action(self, ctx, server_settings, case):
        """Common function after a moderative action."""
        server_settings['casenum'] += 1
        mod_log = discord.utils.get(ctx.message.server.channels, name='mod-log')

        if mod_log is not None:
            msg = await self.bot.send_message(mod_log, str(case))
            case.log_msg = msg.id

        server_settings['cases'].append(case.to_dict())
        await self.set_server_settings(ctx.message.server.id, server_settings)
        await self.bot.say(':ok_hand:')

    def start_lockdown(self, ctx):
        pass

    def end_lockdown(self, ctx):
        pass

    async def on_message_delete(self, message):
        if not message.server:
            return  # PMs
        msg_log = discord.utils.get(message.server.channels, name="message-log")
        if not msg_log:
            return
        embed = discord.Embed()
        embed.title = f"{message.author} deleted a message in {message.channel}."
        if message.content:
            embed.description = message.content
        for attachment in message.attachments:
            embed.add_field(name="Attachment", value=attachment['url'])
        embed.colour = 0xff615b
        embed.set_footer(text="Originally sent")
        embed.timestamp = message.timestamp
        await self.bot.send_message(msg_log, embed=embed)

    async def on_message_edit(self, before, after):
        if not before.server:
            return  # PMs
        msg_log = discord.utils.get(before.server.channels, name="message-log")
        if not msg_log:
            return
        if before.content == after.content:
            return
        embed = discord.Embed()
        embed.title = f"{before.author} edited a message in {before.channel} (below is original message)."
        if before.content:
            embed.description = before.content
        for attachment in before.attachments:
            embed.add_field(name="Attachment", value=attachment['url'])
        embed.colour = 0x5b92ff
        if len(after.content) < 1000:
            new = after.content
        else:
            new = str(after.content)[:1000] + "..."
        embed.add_field(name="New Content", value=new)
        await self.bot.send_message(msg_log, embed=embed)

    async def on_member_join(self, member):
        pass

    async def on_member_ban(self, member):
        pass

    async def on_member_unban(self, server, user):
        pass

    async def on_member_update(self, before, after):
        pass

    async def get_server_settings(self, server_id, projection=None):
        server_settings = await self.bot.mdb.mod.find_one({"server": server_id}, projection)
        if server_settings is None:
            server_settings = get_default_settings(server_id)
        return server_settings

    async def set_server_settings(self, server_id, settings):
        await self.bot.mdb.mod.update_one(
            {"server": server_id},
            {"$set": settings}, upsert=True
        )


def get_default_settings(server):
    return {
        "server": server
    }


class Case:
    def __init__(self, num, type_, user, reason, mod=None, log_msg=None, username=None):
        self.num = num
        self.type = type_
        self.user = user
        self.username = username
        self.reason = reason
        self.mod = mod
        self.log_msg = log_msg

    @classmethod
    def new(cls, num, type_, user, reason, mod=None, username=None):
        return cls(num, type_, user, reason, mod=mod, username=username)

    @classmethod
    def from_dict(cls, raw):
        raw['type_'] = raw.pop('type')
        return cls(**raw)

    def to_dict(self):
        return {"num": self.num, "type": self.type, "user": self.user, "reason": self.reason, "mod": self.mod,
                "log_msg": self.log_msg, "username": self.username}

    def __str__(self):
        if self.username:
            user = f"{self.username} ({self.user})"
        else:
            user = self.user

        if self.mod:
            modstr = self.mod
        else:
            modstr = f"Responsible moderator, do `.reason {self.num} <reason>`"

        return f'**{self.type.title()}** | Case {self.num}\n' \
               f'**User**: {user}\n' \
               f'**Reason**: {self.reason}\n' \
               f'**Responsible Mod**: {modstr}'


def setup(bot):
    bot.add_cog(Moderation(bot))
