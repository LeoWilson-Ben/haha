from django.db import models


class User(models.Model):
    """用户主表，对应架构设计 user 表"""
    mobile = models.CharField(max_length=20, unique=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)
    nickname = models.CharField(max_length=64, null=True, blank=True)
    avatar_url = models.CharField(max_length=512, null=True, blank=True)
    gender = models.SmallIntegerField(null=True, blank=True)
    status = models.SmallIntegerField(default=1)
    minor_mode = models.SmallIntegerField(default=0)
    minor_mode_pwd = models.CharField(max_length=255, null=True, blank=True)
    user_code = models.CharField(max_length=8, null=True, blank=True)
    last_bazi_edit_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user"
        managed = False


class UserWallet(models.Model):
    user_id = models.BigIntegerField(primary_key=True)
    balance = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    frozen_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    version = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_wallet"
        managed = False


class WalletLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField()
    type = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    order_no = models.CharField(max_length=64, null=True, blank=True)
    remark = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wallet_log"
        managed = False


class OrderMain(models.Model):
    id = models.BigAutoField(primary_key=True)
    order_no = models.CharField(max_length=64, unique=True)
    user_id = models.BigIntegerField()
    type = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    pay_channel = models.CharField(max_length=20, null=True, blank=True)
    pay_trade_no = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=20, default="pending")
    subject = models.CharField(max_length=255, null=True, blank=True)
    extra_json = models.TextField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "order_main"
        managed = False


class WithdrawApply(models.Model):
    id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField()
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    bank_card_snapshot = models.CharField(max_length=500, null=True, blank=True)
    status = models.CharField(max_length=20, default="pending")
    audit_by = models.BigIntegerField(null=True, blank=True)
    audit_at = models.DateTimeField(null=True, blank=True)
    remark = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "withdraw_apply"
        managed = False
