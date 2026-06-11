from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponseRedirect
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.conf import settings
import requests
from .models import (
    TelegramGroup,
    MessageTemplate,
    MessageLog,
    ScheduledTask,
    TxTracker,
    TxRateCache,
)
from .services import RateService, ExplorerService, TxService


@login_required
def dashboard(request):
    """Anasayfa - Dashboard"""
    context = {
        'total_groups': TelegramGroup.objects.filter(is_active=True).count(),
        'total_templates': MessageTemplate.objects.filter(is_active=True).count(),
        'total_messages': MessageLog.objects.count(),
        'success_messages': MessageLog.objects.filter(status='success').count(),
        'failed_messages': MessageLog.objects.filter(status='failed').count(),
        'pending_messages': MessageLog.objects.filter(status='pending').count(),
        'recent_logs': MessageLog.objects.all()[:10],
    }
    return render(request, 'core/dashboard.html', context)


@login_required
def group_list(request):
    """Gruplar listesi"""
    groups = TelegramGroup.objects.all()
    return render(request, 'core/groups.html', {'groups': groups})


@require_http_methods(["POST"])
def group_add(request):
    """Grup ekle"""
    name = request.POST.get('name')
    chat_id = request.POST.get('chat_id')
    description = request.POST.get('description', '')
    tx_tracker_enabled = request.POST.get('tx_tracker_enabled') == 'on'

    if TelegramGroup.objects.filter(chat_id=chat_id).exists():
        messages.error(request, 'Bu Chat ID zaten kayıtlı!')
        return redirect('groups')

    TelegramGroup.objects.create(
        name=name,
        chat_id=chat_id,
        description=description,
        tx_tracker_enabled=tx_tracker_enabled,
    )
    messages.success(request, 'Grup başarıyla eklendi!')
    return redirect('groups')


@require_http_methods(["POST"])
def group_delete(request, pk):
    """Grup sil"""
    group = get_object_or_404(TelegramGroup, pk=pk)
    group.delete()
    messages.success(request, 'Grup silindi!')
    return redirect('groups')


@require_http_methods(["POST"])
def group_toggle(request, pk):
    """Grup aktif/pasif durumu değiştir"""
    group = get_object_or_404(TelegramGroup, pk=pk)
    group.is_active = not group.is_active
    group.save()
    status = "aktif" if group.is_active else "pasif"
    messages.success(request, f'Grup {status} hale getirildi!')
    return redirect('groups')


@require_http_methods(["POST"])
def group_toggle_tracker(request, pk):
    """Grup için Kripto TX takibini aç/kapat"""
    group = get_object_or_404(TelegramGroup, pk=pk)
    group.tx_tracker_enabled = not group.tx_tracker_enabled
    group.save()
    state = "aktifleştirildi" if group.tx_tracker_enabled else "devre dışı bırakıldı"
    messages.success(request, f'Kripto TX takibi {group.name} için {state}.')
    return redirect('groups')


@login_required
def settings_view(request):
    """Ayarlar sayfası"""
    if request.method == 'POST':
        # Bot token güncelleme
        main_bot_token = request.POST.get('main_bot_token')
        if main_bot_token:
            from django.conf import settings
            settings.TELEGRAM_BOT_TOKEN = main_bot_token
            messages.success(request, 'Ana bot token güncellendi!')
        return redirect('settings')
    
    groups = TelegramGroup.objects.filter(is_active=True)
    return render(request, 'core/settings.html', {'groups': groups})


@login_required
def templates(request):
    """Hazır mesaj şablonları"""
    templates = MessageTemplate.objects.all()
    return render(request, 'core/templates.html', {'templates': templates})


@require_http_methods(["POST"])
def template_add(request):
    """Şablon ekle"""
    name = request.POST.get('name')
    content = request.POST.get('content')
    description = request.POST.get('description', '')
    
    MessageTemplate.objects.create(
        name=name,
        content=content,
        description=description
    )
    messages.success(request, 'Şablon başarıyla eklendi!')
    return redirect('templates')


@require_http_methods(["POST"])
def template_edit(request, pk):
    """Şablon düzenle"""
    template = get_object_or_404(MessageTemplate, pk=pk)
    template.name = request.POST.get('name')
    template.content = request.POST.get('content')
    template.description = request.POST.get('description', '')
    template.save()
    messages.success(request, 'Şablon güncellendi!')
    return redirect('templates')


@require_http_methods(["POST"])
def template_delete(request, pk):
    """Şablon sil"""
    template = get_object_or_404(MessageTemplate, pk=pk)
    template.delete()
    messages.success(request, 'Şablon silindi!')
    return redirect('templates')


@login_required
def send_message_view(request):
    """Mesaj gönderim sayfası"""
    groups = TelegramGroup.objects.filter(is_active=True)
    templates = MessageTemplate.objects.filter(is_active=True)
    return render(request, 'core/send_message.html', {
        'groups': groups,
        'templates': templates
    })


@require_http_methods(["POST"])
def send_message(request):
    """Mesaj gönder"""
    message_content = request.POST.get('message')
    selected_groups = request.POST.getlist('groups')
    use_template = request.POST.get('use_template')
    
    if use_template:
        template = get_object_or_404(MessageTemplate, pk=use_template)
        message_content = template.content
    
    if not message_content:
        messages.error(request, 'Mesaj içeriği boş olamaz!')
        return redirect('send_message')
    
    if not selected_groups:
        messages.error(request, 'En az bir grup seçmelisiniz!')
        return redirect('send_message')
    
    groups = TelegramGroup.objects.filter(id__in=selected_groups, is_active=True)
    
    # Log oluştur
    log = MessageLog.objects.create(
        message_content=message_content,
        status='pending'
    )
    log.groups.set(groups)
    
    # Mesajları gönder (ayarlardaki ana token kullanılacak)
    from django.conf import settings
    bot_token = settings.TELEGRAM_BOT_TOKEN
    
    sent_count = 0
    failed_count = 0
    
    for group in groups:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': group.chat_id,
                'text': message_content
            }
            response = requests.post(url, data=data, timeout=10)
            
            if response.status_code == 200:
                sent_count += 1
            else:
                failed_count += 1
        except Exception as e:
            failed_count += 1
    
    # Log güncelle
    log.sent_count = sent_count
    log.failed_count = failed_count
    log.sent_at = timezone.now()
    log.status = 'success' if sent_count > 0 else 'failed'
    log.save()
    
    messages.success(
        request, 
        f'Mesaj gönderimi tamamlandı! Başarılı: {sent_count}, Başarısız: {failed_count}'
    )
    return redirect('send_message')


def get_logs(request):
    """Logları JSON olarak döndür"""
    logs = MessageLog.objects.all()[:50]
    data = [{
        'id': log.id,
        'message_content': log.message_content[:100],
        'status': log.status,
        'sent_count': log.sent_count,
        'failed_count': log.failed_count,
        'created_at': log.created_at.strftime('%d.%m.%Y %H:%M'),
        'sent_at': log.sent_at.strftime('%d.%m.%Y %H:%M') if log.sent_at else '-',
    } for log in logs]
    return JsonResponse({'logs': data})


def get_template(request, pk):
    """Şablon içeriğini JSON olarak döndür"""
    template = get_object_or_404(MessageTemplate, pk=pk)
    return JsonResponse({
        'id': template.id,
        'name': template.name,
        'content': template.content,
        'description': template.description
    })


@login_required
def scheduled_tasks(request):
    """Planlanmış görevler sayfası"""
    tasks = ScheduledTask.objects.all().prefetch_related('groups')
    groups = TelegramGroup.objects.filter(is_active=True)
    templates = MessageTemplate.objects.filter(is_active=True)
    return render(request, 'core/scheduled_tasks.html', {
        'tasks': tasks,
        'groups': groups,
        'templates': templates
    })


@require_http_methods(["POST"])
def scheduled_task_add(request):
    """Planlanmış görev ekle"""
    name = request.POST.get('name')
    template_id = request.POST.get('template_id')
    interval_minutes = request.POST.get('interval_minutes', 60)
    selected_groups = request.POST.getlist('groups')
    
    if not selected_groups:
        messages.error(request, 'En az bir grup seçmelisiniz!')
        return redirect('scheduled_tasks')
    
    template = get_object_or_404(MessageTemplate, pk=template_id)
    
    task = ScheduledTask.objects.create(
        name=name,
        template=template,
        interval_minutes=int(interval_minutes)
    )
    task.groups.set(selected_groups)
    
    messages.success(request, 'Planlanmış görev oluşturuldu!')
    return redirect('scheduled_tasks')


@require_http_methods(["POST"])
def scheduled_task_toggle(request, pk):
    """Planlanmış görev aktif/pasif"""
    task = get_object_or_404(ScheduledTask, pk=pk)
    task.is_active = not task.is_active
    task.save()
    status = "aktifleştirildi" if task.is_active else "pasifleştirildi"
    messages.success(request, f'Görev {status}!')
    return redirect('scheduled_tasks')


@require_http_methods(["POST"])
def scheduled_task_delete(request, pk):
    """Planlanmış görev sil"""
    task = get_object_or_404(ScheduledTask, pk=pk)
    task.delete()
    messages.success(request, 'Görev silindi!')
    return redirect('scheduled_tasks')


@require_http_methods(["POST"])
def scheduled_task_edit(request, pk):
    """Planlanmış görev düzenle"""
    task = get_object_or_404(ScheduledTask, pk=pk)
    task.name = request.POST.get('name')
    template_id = request.POST.get('template_id')
    interval_minutes = request.POST.get('interval_minutes', 60)
    selected_groups = request.POST.getlist('groups')
    
    if template_id:
        task.template = get_object_or_404(MessageTemplate, pk=template_id)
    task.interval_minutes = int(interval_minutes)
    task.save()

    if selected_groups:
        task.groups.set(selected_groups)

    messages.success(request, 'Görev güncellendi!')
    return redirect('scheduled_tasks')


# =====================================================================
# Kripto TX Takip Modülü
# =====================================================================

@login_required
def tx_tracker_dashboard(request):
    """Kripto takip ana sayfası: istatistikler, son tx'ler, aktif gruplar."""
    tx_qs = TxTracker.objects.all()
    stats = {
        'total': tx_qs.count(),
        'resolved': tx_qs.filter(status='resolved').count(),
        'pending': tx_qs.filter(status='pending').count(),
        'failed': tx_qs.filter(status='failed').count(),
        'ignored': tx_qs.filter(status='ignored').count(),
        'total_try_value': sum(
            (t.try_value for t in tx_qs.filter(status='resolved') if t.try_value),
            start=Decimal('0'),
        ),
    }
    enabled_groups = TelegramGroup.objects.filter(is_active=True, tx_tracker_enabled=True)
    return render(
        request,
        'core/tx_tracker.html',
        {
            'stats': stats,
            'recent_tx': tx_qs[:30],
            'enabled_groups': enabled_groups,
            'all_groups': TelegramGroup.objects.all().order_by('name'),
            'rate_cache': TxRateCache.objects.all()[:20],
        },
    )


@login_required
@require_http_methods(["POST"])
def tx_lookup(request):
    """Manuel tx arama - admin panelinden hash girip sonucu gör."""
    tx_hash = (request.POST.get('tx_hash') or '').strip()
    asset_hint = (request.POST.get('asset_hint') or '').strip().upper() or None

    if not tx_hash:
        messages.error(request, 'Tx hash boş olamaz.')
        return redirect('tx_tracker')

    explorer = ExplorerService()
    rate_service = RateService()
    details = explorer.fetch(tx_hash)
    result = {'tx_hash': tx_hash, 'ok': False, 'details': None, 'error': None, 'rate': None, 'value': None}

    if details is None:
        result['error'] = 'Zincir/format desteklenmiyor veya explorer verisi alınamadı.'
    else:
        symbol = (asset_hint or details.asset_symbol or 'USDT').upper()
        try:
            amount = Decimal(str(details.amount)) if details.amount is not None else Decimal('0')
        except Exception:  # noqa: BLE001
            amount = Decimal('0')
        rate_info = rate_service.get_try_rate(symbol)
        rate = rate_info.get('rate') if rate_info else None
        value = (amount * rate).quantize(Decimal('0.01')) if rate and amount else None
        result.update({
            'ok': True,
            'details': details,
            'rate': rate,
            'value': value,
            'symbol': symbol,
            'source': (rate_info or {}).get('source'),
        })

    return render(
        request,
        'core/tx_tracker.html',
        {
            'stats': _tx_stats(),
            'recent_tx': TxTracker.objects.all()[:30],
            'enabled_groups': TelegramGroup.objects.filter(is_active=True, tx_tracker_enabled=True),
            'all_groups': TelegramGroup.objects.all().order_by('name'),
            'rate_cache': TxRateCache.objects.all()[:20],
            'lookup_result': result,
        },
    )


@login_required
@require_http_methods(["POST"])
def tx_enable_group(request, pk):
    """Tek bir grup için tx takibini aç."""
    group = get_object_or_404(TelegramGroup, pk=pk)
    group.tx_tracker_enabled = True
    group.is_active = True
    group.save()
    messages.success(request, f'{group.name} için kripto takibi aktifleştirildi.')
    return redirect('tx_tracker')


@login_required
@require_http_methods(["POST"])
def tx_disable_group(request, pk):
    """Tek bir grup için tx takibini kapat."""
    group = get_object_or_404(TelegramGroup, pk=pk)
    group.tx_tracker_enabled = False
    group.save()
    messages.success(request, f'{group.name} için kripto takibi devre dışı bırakıldı.')
    return redirect('tx_tracker')


@login_required
def tx_rates_api(request):
    """Anlık kur cache'ini JSON olarak döner (UI otomatik yenileme için)."""
    rows = [
        {
            'asset': r.asset,
            'source': r.source,
            'pair': r.pair,
            'rate': str(r.rate),
            'fetched_at': r.fetched_at.strftime('%d.%m.%Y %H:%M:%S'),
        }
        for r in TxRateCache.objects.all()[:20]
    ]
    return JsonResponse({'rates': rows})


@login_required
@require_http_methods(["POST"])
def tx_send_test(request, pk):
    """Belirli bir gruba örnek tx hash gönderip botun nasıl cevap vereceğini test eder.
    Gerçek bir test: bot sanki gruptaymış gibi çalışır, cevabı panelde gösterir."""
    from core.services import TxService  # geç import

    group = get_object_or_404(TelegramGroup, pk=pk)
    sample_hash = 'f7f0b5c6c7fba0fef478033aea57035588f61475182322fd774d80a48e91f95e'
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')

    # Eğer tx_tracker_enabled değilse kullanıcıyı uyar
    if not group.is_active:
        messages.error(request, f'{group.name} pasif durumda. Önce aktifleştirin.')
        return redirect('tx_tracker')
    if not group.tx_tracker_enabled:
        messages.warning(request, f'{group.name} için TX takibi kapalı. Test mesajı yine de gönderildi ama bot cevap vermeyecek.')

    if not bot_token:
        messages.error(request, 'TELEGRAM_BOT_TOKEN tanımlı değil.')
        return redirect('tx_tracker')

    # Botu sanki gruptaymış gibi çalıştır (sadece hesaplama)
    svc = TxService(bot_token=bot_token)
    text = (
        f"Test mesajı - gerçek bir örnek\n\n"
        f"Tether 5,360 gönderildi.\n\n"
        f"Tx: {sample_hash}\n"
        f"https://tronscan.org/#/transaction/{sample_hash}"
    )
    try:
        reply = svc.process(
            message_text=text,
            chat_id=group.chat_id,
            message_id=None,
        )
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f'Hata: {exc}')
        return redirect('tx_tracker')

    if not reply:
        result_text = (
            '⚠ Bot bir yanıt üretmedi. Olası sebepler:\n'
            '1) Bot gruba admin olarak eklenmemiş olabilir\n'
            '2) Webhook kurulu olmayabilir (/webhook/set/ adresini ziyaret edin)\n'
            '3) Explorer servisi geçici olarak cevap vermiyor olabilir'
        )
    else:
        result_text = f'✅ Bot şu yanıtı üretecek:\n\n{reply}'

    # Test mesajını kendi adımıza gruba da gönderelim (gerçek simülasyon)
    # NOT: Bu, sadece bir simülasyon; webhook'tan geçmiyor, sadece mesajı gruba yollar
    # İsterseniz bu kısmı kaldırabiliriz, çünkü sadece formatı görmek istiyorsanız üstteki yeter.
    # Kullanıcıya inline sonuç göstermek için session flash yerine
    # query string üzerinden dönelim ve template'te gösterelim.
    request.session['tx_test_result'] = result_text
    request.session['tx_test_group'] = group.name
    return HttpResponseRedirect('/kripto/?test=1')


@login_required
def tx_clear_test_result(request):
    request.session.pop('tx_test_result', None)
    request.session.pop('tx_test_group', None)
    return redirect('tx_tracker')


def _tx_stats():
    tx_qs = TxTracker.objects.all()
    return {
        'total': tx_qs.count(),
        'resolved': tx_qs.filter(status='resolved').count(),
        'pending': tx_qs.filter(status='pending').count(),
        'failed': tx_qs.filter(status='failed').count(),
        'ignored': tx_qs.filter(status='ignored').count(),
        'total_try_value': sum(
            (t.try_value for t in tx_qs.filter(status='resolved') if t.try_value),
            start=Decimal('0'),
        ),
    }
