import logging

from typing import Union

from discord.ext import commands


class ReactForRole(commands.Cog, name="React for Role"):
    def __init__(self, bot):
        self.bot = bot
        self.db_conn_cog = None
        self.logger = logging.getLogger("SVGEBot.RoleReact")
        self.logger.info("Loaded ReactForRole")

    @property
    def cmd_prefix(self):
        return self.bot.bot_config['cmd_prefix']

    def cog_unload(self):
        self.logger.info("Unloaded ReactForRole")

    @commands.Cog.listener()
    async def on_ready(self):
        self.db_conn_cog = self.bot.get_cog("DBConnPool")

    async def cog_check(self, ctx):
        """This method is a cog wide check to ensure users have "admin" roles,

        It will be called without the need for check decorators on every command.
        """
        for role in ctx.message.author.roles:
            if role.id in self.bot.bot_config["admin_role_id_list"]:
                return True
        return False

    @commands.group(name="rfr")
    async def react_for_role_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send(f"You need to use a subcommand with this command group.\n\n"
                           f"Use `{self.cmd_prefix}help rfr` to see child commands.")

    @react_for_role_group.group(name="message")
    async def rfr_message_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send(f"You need to use a subcommand with this command group.\n\n"
                           f"Use `{self.cmd_prefix}help rfr message` to see child commands.")

    @rfr_message_group.command(name="create")
    @commands.guild_only()
    async def rfr_message_create(self, ctx, channel_id):
        guild_db_name = "guild_"+str(ctx.guild.id)
        target_channel = ctx.guild.get_channel(int(channel_id))
        if target_channel is None:
            await ctx.send("Invalid channel id, try again.", delete_after=self.bot.delete_msg_after)
            self.logger.debug(f"{ctx.author} attempted to create an rfr message but failed to "
                              f"supply a valid channel ID.")
            return
        async with self.db_conn_cog.conn_pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("USE `%s`", guild_db_name)
                await cursor.execute("""
                    INSERT INTO r_for_r_messages (r_for_r_id, message_id) 
                    VALUES (DEFAULT, NULL);
                    SELECT LAST_INSERT_ID()
                """)
                current_rfr_id = await cursor.fetchone()
                await cursor.execute("""
                    CREATE TABLE %(rfr_id)s (
                        rfr_relation_id INT
                    )
                """, {"rfr_id": f"rfr_emoji_{str(current_rfr_id)}"})

        await ctx.send(f"Created rfr with id: {str(current_rfr_id)}.\n\n"
                       f"Do not lose this identifier.")

    async def __create_new_rfr_relation(self, emoji_id, role_id, rfr_name, ctx):
        """Create a new rfr record.

        :param emoji_id: Emoji ID
        :param role_id: Role ID
        :param rfr_name: Name of rfr relation
        :param ctx: Command context

        :return: rfr relation_id or None.
        :rtype: Union[int, NoneType]"""
        guild_db_name = "guild_"+str(ctx.guild.id)
        emoji_object = self.bot.get_emoji(int(emoji_id))
        if emoji_object is None:
            await ctx.send("Invalid emoji ID supplied.", delete_after=self.bot.delete_msg_after)
            return None
        role_object = self.bot.get_guild(int(ctx.guild.id)).get_role(int(role_id))
        if role_object is None:
            await ctx.send("Invalid role ID supplied.", delete_after=self.bot.delete_msg_after)
            return None
        
        async with self.db_conn_cog.conn_pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("USE `%s`", guild_db_name)
                await cursor.execute("""
                    INSERT INTO r_for_r_emoji
                    (relation_id, role_id, emoji_id, name) VALUES 
                    (DEFAULT, %(role_id)s, %(emoji_id)s, %(rfr_name)s);
                    SELECT LAST_INSERT_ID()
                """, {"role_id": role_id, "emoji_id": emoji_id, "rfr_name": rfr_name})
                return await cursor.fetchone()

    @rfr_message_group.command(name="add")
    @commands.guild_only()
    async def rfr_message_add_rfr(self, ctx, rfr_msg_id, *, addition):
        """Add either a pre-existing rfr relation or a new rfr relation
        to a preexisting rfr message.

        :param ctx: Auto-filled by library
        :param rfr_msg_id: ID of rfr message to add an emoji to
        :param addition: rfr to add, may be in one of two forms:
            1) `<r_for_r_emoji_relation_id>`
            2) `<emoji_id>,<role_id>,<rfr_name(may contain spaces)>`
        """
        split_addition = addition.split(",")
        if len(split_addition) > 3 or len(split_addition) == 0:
            self.logger.debug(f"Addition parameter was passed as {addition}, "
                              f"upon splitting yielded: {split_addition}.")
            await ctx.send("Invalid `addition` argument supplied.",
                           delete_after=self.bot.delete_msg_after)
            return
        guild_db_name = "guild_"+str(ctx.guild.id)
        # Figure out on which conditional path we need to go
        need_to_make_new_rfr_relation = len(split_addition) == 3
        if need_to_make_new_rfr_relation:
            rfr_relation_id = await self.__create_new_rfr_relation(*split_addition, ctx)
            if rfr_relation_id is None:
                return
        else:
            rfr_relation_id = addition
        async with self.db_conn_cog.conn_pool.acquire() as connection:
            async with connection.cursor() as cursor:
                # Check whether or not the addressed rfr message exists
                await cursor.execute("""
                    SELECT count(*)
                    FROM information_schema.TABLES
                    WHERE (TABLE_SCHEMA = %(db_name)s) AND (TABLE_NAME = %(table_name)s)
                """, {"db_name": guild_db_name, "table_name": f"rfr_emoji_{str(rfr_msg_id)}"})
                if not bool(await cursor.fetchone()):
                    await ctx.send("You have supplied an invalid rfr identifier, please try "
                                   "again", delete_after=self.bot.delete_msg_after)
                    return
                await cursor.execute("USE `%s`", guild_db_name)
                await cursor.execute("""
                    INSERT INTO %(rfr_msg_obj_id)s (rfr_relation_id)
                    VALUE (%(rfr_emoji_role_id)s)
                """, {"rfr_msg_obj_id": rfr_msg_id,
                      "rfr_emoji_role_id": rfr_relation_id})
        await ctx.send(f'Added emoji: "{self.bot.get_emoji(int(split_addition[0]))}" to rfr '
                       f'message with ID: "{rfr_msg_id}." To test how this message will look, '
                       f'send: `>>rfr message test {rfr_msg_id}`')


def setup(bot):
    bot.add_cog(ReactForRole(bot))
