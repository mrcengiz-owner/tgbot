from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
import requests
from .models import TelegramGroup, MessageTemplate, MessageLog


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
    
    if TelegramGroup.objects.filter(chat_id=chat_id).exists():
        messages.error(request, 'Bu Chat ID zaten kayıtlı!')
        return redirect('groups')
    
    TelegramGroup.objects.create(
        name=name,
        chat_id=chat_id,
        description=description
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
