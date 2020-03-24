import logging
import re
import datetime

from discord.ext import commands


class UserVerification(commands.Cog, name="User Verification"):
    def __init__(self, bot):
        self.bot = bot
        self.db_pool_cog = None
        self.logger = logging.getLogger("SVGEBot.Verification")
        self.logger.info("Loaded User Verification")

    @property
    def cmd_prefix(self):
        return self.bot.bot_config['cmd_prefix']

    @commands.Cog.listener()
    async def on_ready(self):
        self.db_pool_cog = self.bot.get_cog("DBConnPool")

    async def __add_member_to_database(self, member):
        guild_db_name = "guild_" + str(member.guild.id)
        async with self.db_pool_cog.conn_pool.acquire() as db_conn:
            async with db_conn.cursor() as cursor:
                await cursor.execute("USE `%s`", (guild_db_name,))
                # Create the user records, very old datetime used to ensure the first
                # verification attempt will be allowed. There is a one minute ratelimit
                # on verification request having emails, rather than on the command scale.
                await cursor.execute(
                    """SELECT discord_user_id
                    FROM guild_members
                    WHERE discord_user_id = %s""",
                    (member.id,)
                )
                user_already_exists = bool(await cursor.fetchall())

                await cursor.execute(
                    """INSERT INTO guild_members (
                        discord_user_id, discord_username, verified
                    ) VALUES (%(d_uid)s, %(d_uname)s, 0) 
                    ON DUPLICATE KEY UPDATE discord_username=(%(d_uname)s);
                    INSERT INTO member_verification (
                        discord_user_id, email, verification_key, last_verification_req
                    ) VALUES (%(d_uid)s, '', '', %(datetime_old)s)
                    ON DUPLICATE KEY UPDATE discord_user_id=discord_user_id""",
                    {"d_uid": member.id, "d_uname": member.name+"#"+member.discriminator,
                     "datetime_old": datetime.datetime(2000, 1, 1)}
                )

                return user_already_exists

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not await self.__add_member_to_database(member):
            await member.send(
                f"Welcome to {member.guild.name}.\n\n"
                f"{member.guild.name} only allows verified accounts to join. "
                f"In the case that you are an alumni, please contact a member "
                f"of the administrative team for assistance.\n\n"
                f"In order to verify, you will need to provide a University of "
                f"Southampton (@soton.ac.uk) email address in this DM.\n\n"
                f"The command will look something like:\n"
                f"`{self.cmd_prefix}verify <your_soton_email_address> {member.guild.id}`."
            )

    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    @commands.command()
    async def bulk_member_registration(self, ctx):
        for member in ctx.guild.members:
            if not await self.__add_member_to_database(member):
                await member.send(
                    f"You have been added to {member.guild.name}'s verification system."
                    f"In order to verify, you will need to provide a University of "
                    f"Southampton (@soton.ac.uk) email address in this DM.\n\n"
                    f"The command will look something like:\n"
                    f"`{self.cmd_prefix}verify <your_soton_email_address> {member.guild.id}`."
                )

    @commands.command()
    @commands.dm_only()
    async def verify(self, ctx, email_address, pre_verification_id):
        """Allows users to begin the verification process in a given discord guild.

        :param ctx: Command context, internally provided.
        :param email_address: Email address, must satisfy given conditions.
        :type email_address: str
        :param pre_verification_id: ID required to start verification process.
        :type pre_verification_id: int"""
        try:
            guild_id = int(pre_verification_id)
        except ValueError:
            await ctx.send("You have provided an invalid pre-verification id.")
            return

        soton_email_regex_pattern = r"[\w\.]{3,64}\@soton\.ac\.uk"

        regex_result = re.search(soton_email_regex_pattern, email_address)
        if regex_result is None:
            await ctx.send("You have provided an invalid email address. Please "
                           "make sure you submit a valid @soton.ac.uk email address")
            return

        command_datetime = datetime.datetime.now()

        guild_table_name = "guild_"+str(guild_id)+""
        async with self.db_pool_cog.conn_pool.acquire() as loc_connection:
            async with loc_connection.cursor() as cursor:
                await cursor.execute(
                    """SELECT SCHEMA_NAME
                        FROM information_schema.SCHEMATA
                        WHERE SCHEMA_NAME = %s""",
                    ("'"+guild_table_name+"'",)
                )
                table_exists = bool(await cursor.fetchall())
                if not table_exists:
                    await ctx.send("You have provided an invalid pre-verification id.")
                    return
                await cursor.execute("USE `%s`", (guild_table_name,))
                await cursor.execute(
                    """SELECT * 
                    FROM guild_members
                    WHERE discord_user_id = %s""",
                    (ctx.author.id,)
                )
                user_result = await cursor.fetchone()
                self.logger.debug(f"User member record found: {user_result}")

                if user_result[3] == 1:
                    await ctx.send("You have already been verified, if you think "
                                   "this is a mistake, please contact an administrator.")
                    return

                await cursor.execute(
                    """SELECT *
                    FROM member_verification
                    WHERE discord_user_id = %s""",
                    (ctx.author.id,)
                )
                user_verification_result = await cursor.fetchone()
                verification_request_timediff = command_datetime - user_verification_result[3]
                if verification_request_timediff < datetime.timedelta(minutes=1):
                    await ctx.send("Please wait before attempting to resend this command, "
                                   "if you have been waiting over 15 minutes for your "
                                   "verification email, please contact an administrator.")
                    return


def setup(bot):
    bot.add_cog(UserVerification(bot))

