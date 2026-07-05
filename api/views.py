# 1. Standart Python Kütüphaneleri
import os
import json
import re
import uuid

# 2. Üçüncü Parti Kütüphaneler (Google API, FitZ vb.)
import requests
import fitz  # PyMuPDF (PDF okumak için)
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build

# 3. Django Çekirdek Kütüphaneleri
from django.contrib.auth.models import User
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

# 4. Django REST Framework (DRF) Kütüphaneleri
from rest_framework import permissions, status, views
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, IsAdminUser

# 5. E-Teacher Projesi Kendi Modellerimiz
from .models import UserActivity, UserProfile, Lesson, GoogleCalendarCredential

from rest_framework import generics


GROQ_CHAT_COMPLETIONS_URL = 'https://api.groq.com/openai/v1/chat/completions'
GROQ_DEFAULT_MODEL = 'openai/gpt-oss-20b'


def request_groq_completion(messages, *, response_format=None, temperature=0.4, max_completion_tokens=2048):
    """Groq'nun OpenAI uyumlu Chat Completions endpoint'ine istek atar."""
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        raise RuntimeError('GROQ_API_KEY ortam değişkeni tanımlı değil.')

    payload = {
        'model': os.environ.get('GROQ_MODEL', GROQ_DEFAULT_MODEL),
        'messages': messages,
        'temperature': temperature,
        'max_completion_tokens': max_completion_tokens,
    }
    if response_format:
        payload['response_format'] = response_format

    return requests.post(
        GROQ_CHAT_COMPLETIONS_URL,
        json=payload,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        timeout=60,
    )
from .serializers import LessonSerializer # Yukarıda oluşturduğumuz serializer

# --- ADMİN KOTA VE KULLANICI YÖNETİMİ ---

class AdminUserListView(views.APIView):
    """Tüm kullanıcıları ve mevcut kredilerini listeler"""
    permission_classes = [IsAdminUser]

    def get(self, request):
        from django.contrib.auth.models import User
        users = User.objects.all()
        user_list = []
        for user in users:
            # Profil varsa krediyi al, yoksa 0 de
            credits = user.profile.ai_credits if hasattr(user, 'profile') else 0
            user_list.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'ai_credits': credits,
                'is_staff': user.is_staff
            })
        return Response(user_list)

class AdminUpdateQuotaView(views.APIView):
    """Belirli bir kullanıcının kotasını günceller"""
    permission_classes = [IsAdminUser]

    def post(self, request):
        user_id = request.data.get('user_id')
        new_credits = request.data.get('ai_credits')

        try:
            from django.contrib.auth.models import User
            target_user = User.objects.get(id=user_id)
            
            # Kullanıcının profili varsa güncelle, yoksa oluştur
            profile, created = UserProfile.objects.get_or_create(user=target_user)
            profile.ai_credits = new_credits
            profile.save()

            return Response({
                'message': f'{target_user.username} için yeni kredi sınırı: {new_credits}'
            })
        except User.DoesNotExist:
            return Response({'error': 'Kullanıcı bulunamadı.'}, status=404)

# --- ADMİN KULLANICI VE PREMİUM YÖNETİMİ ---

class AdminUserManagementView(views.APIView):
    """Tüm kullanıcıları listeler ve premium/kota durumlarını yönetir"""
    permission_classes = [IsAdminUser]

    def get(self, request):
        from django.contrib.auth.models import User
        users = User.objects.all()
        user_list = []
        for user in users:
            # Profil verilerini çekiyoruz
            profile = getattr(user, 'profile', None)
            user_list.append({
                'id': user.id,
                'username': user.username,
                'ai_credits': profile.ai_credits if profile else 0,
                'is_premium': profile.is_premium if profile else False,
                'is_staff': user.is_staff
            })
        return Response(user_list)

    def post(self, request):
        """Kullanıcının premium durumunu veya kredisini günceller"""
        user_id = request.data.get('user_id')
        new_credits = request.data.get('ai_credits')
        set_premium = request.data.get('is_premium') # True veya False gelir

        try:
            target_user = User.objects.get(id=user_id)
            profile, created = UserProfile.objects.get_or_create(user=target_user)
            
            if new_credits is not None:
                profile.ai_credits = new_credits
            
            if set_premium is not None:
                profile.is_premium = set_premium
                
            profile.save()

            return Response({
                'message': f'{target_user.username} başarıyla güncellendi.',
                'is_premium': profile.is_premium,
                'current_credits': profile.ai_credits
            })
        except User.DoesNotExist:
            return Response({'error': 'Kullanıcı bulunamadı.'}, status=404)

# --- 1. KULLANICI PROFİLİ VE KOTA (Görüntüleme / Güncelleme) ---
class UserProfileView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        ai_credits = 0
        if hasattr(user, 'profile'):
            ai_credits = user.profile.ai_credits
            
        return Response({
            'username': user.username,
            'email': user.email,
            'ai_credits': ai_credits,
            'is_calendar_connected': hasattr(user, 'calendar_credential')
        })

    def put(self, request):
        user = request.user
        new_username = request.data.get('username', '').strip()
        new_password = request.data.get('password', '').strip()

        # E-posta değişiyorsa kesin format kontrolü (@ ve . zorunlu)
        if new_username:
            email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_regex, new_username):
                return Response({'error': 'Lütfen geçerli bir e-posta adresi giriniz.'}, status=400)
            
            if User.objects.filter(username=new_username).exclude(id=user.id).exists():
                return Response({'error': 'Bu e-posta adresi başka bir kullanıcı tarafından kullanılıyor.'}, status=400)
            
            user.username = new_username
            user.email = new_username
        
        # Yeni şifre girilmişse kesin güvenlik kontrolü (8 Karakter, Harf ve Rakam zorunlu)
        if new_password:
            if len(new_password) < 8:
                return Response({'error': 'Şifreniz en az 8 karakter olmalıdır.'}, status=400)
            if not re.search(r"[A-Za-z]", new_password) or not re.search(r"[0-9]", new_password):
                return Response({'error': 'Şifreniz en az bir harf ve bir rakam içermelidir.'}, status=400)
            
            user.set_password(new_password)
            
        user.save()
        return Response({'message': 'Profil başarıyla güncellendi.'}, status=status.HTTP_200_OK)


# --- 2. KULLANICI KAYIT İŞLEMİ (EKSİK OLAN VE DÜZELTİLEN KISIM BURASI) ---
class RegisterView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        password = request.data.get('password', '').strip()
        
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            return Response({'error': 'Lütfen geçerli bir e-posta adresi giriniz.'}, status=400)

        if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
            return Response({'error': 'Şifreniz en az 8 karakter olmalı, harf ve rakam içermelidir.'}, status=400)

        if User.objects.filter(username=email).exists():
            return Response({'error': 'Bu email zaten kullanılıyor.'}, status=400)
            
        try:
            user = User.objects.create_user(username=email, email=email, password=password)
            UserProfile.objects.create(user=user, ai_credits=20)
            return Response({'message': 'Kayıt başarılı, giriş yapabilirsiniz.'}, status=201)
        except Exception as e:
            return Response({'error': 'Kayıt sırasında teknik bir hata oluştu.'}, status=500)


# --- 3. KENDİ ML (MAKİNE ÖĞRENMESİ) MODELLERİMİZ ---
class MLExamAnalysisView(views.APIView):
    permission_classes = [permissions.AllowAny] 

    def post(self, request):
        subjects = request.data.get('subjects', [])
        toplam_net = sum([float(s.get('net', 0)) for s in subjects])
        analysis = f"Özel ML Modelimizin Çıktısı: Toplam netiniz {toplam_net}. Matris analizine göre Fen dersine yüklenmelisiniz."
        return Response({'analysis': analysis})

class MLTargetNetsView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        university = request.data.get('university')
        department = request.data.get('department')
        return Response({
            'tyt_requirement': '95.5',
            'ayt_requirement': '68.25',
            'analysis': f'ML Modelimize göre {university} - {department} için güvenli bölgedesiniz.'
        })


# --- 4. HAZIR API (GROQ KULLANILARAK - KOTA DÜŞÜRENLER) ---
class APIChatView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        profile = getattr(request.user, 'profile', None)
        if profile and profile.ai_credits <= 0:
            return Response({'error': 'Yapay zeka kullanım kotanız dolmuştur.'}, status=403)

        message = request.data.get('message', '')
        if not message:
            return Response({'error': 'Mesaj içeriği boş olamaz.'}, status=400)

        try:
            resp = request_groq_completion(
                messages=[
                    {'role': 'system', 'content': 'Sen şefkatli, anlayışlı ve motive edici bir rehber öğretmen/psikologsun. Sınav stresi çeken öğrencilere kısa, net ve rahatlatıcı tavsiyeler ver. Çok uzun yazma.'},
                    {'role': 'user', 'content': message}
                ],
                temperature=0.6,
                max_completion_tokens=700,
            )
            
            if resp.ok:
                if profile:
                    profile.ai_credits -= 1
                    profile.save()
                reply = resp.json()['choices'][0]['message']['content']
                return Response({'reply': reply})
            else:
                return Response({'error': f'Yapay zeka servisine ulaşılamadı. Hata Kodu: {resp.status_code}'}, status=400)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

class APISummaryView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        profile = getattr(request.user, 'profile', None)
        if profile and profile.ai_credits <= 0:
            return Response({'error': 'Yapay zeka kullanım kotanız dolmuştur.'}, status=403)

        text = request.data.get('text', '')
        try:
            resp = request_groq_completion(
                messages=[
                    {'role': 'system', 'content': 'Gönderilen uzun metinleri veya ders notlarını okuyup, en önemli kısımlarını anlaşılır ve akılda kalıcı maddeler halinde özetleyen bir asistansın. Türkçe yanıt ver.'},
                    {'role': 'user', 'content': f"Şu metni benim için özetle:\n\n{text}"}
                ],
                temperature=0.3,
                max_completion_tokens=1800,
            )
            
            if resp.ok:
                if profile:
                    profile.ai_credits -= 1
                    profile.save()
                summary = resp.json()['choices'][0]['message']['content']
                return Response({'summary': summary})
            else:
                return Response({'error': 'Özetleme servisine ulaşılamadı.'}, status=400)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

class APIQuizGenerateView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        profile = getattr(request.user, 'profile', None)
        if profile and profile.ai_credits <= 0:
            return Response({'error': 'Yapay zeka kullanım kotanız dolmuştur.'}, status=403)

        topic = request.data.get('topic', 'Genel Kültür')
        difficulty = request.data.get('difficulty', 'Orta')
        try:
            count = max(1, min(int(request.data.get('count', 5)), 20))
        except (TypeError, ValueError):
            count = 5
        
        prompt = f"""
        Lütfen '{topic}' konusunda, '{difficulty}' zorluk derecesinde {count} soruluk çoktan seçmeli bir test hazırla.
        Tam olarak {count} soru üret. Yanıtın yalnızca "quiz" alanını içeren bir JSON nesnesi olsun;
        Markdown, kod bloğu, başlık veya açıklama ekleme. Her soru aşağıdaki dört alanı eksiksiz içersin:
        {{"quiz": [
          {{
            "question": "Soru metni buraya gelecek",
            "options": ["Seçenek A", "Seçenek B", "Seçenek C", "Seçenek D", "Seçenek E"],
            "correctAnswer": "Doğru olan seçeneğin tam metni",
            "explanation": "Bu cevabın neden doğru olduğunun açıklaması"
          }}
        ]}}
        """
        
        try:
            quiz_schema = {
                'type': 'object',
                'properties': {
                    'quiz': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'question': {'type': 'string'},
                                'options': {
                                    'type': 'array',
                                    'items': {'type': 'string'},
                                },
                                'correctAnswer': {'type': 'string'},
                                'explanation': {'type': 'string'},
                            },
                            'required': ['question', 'options', 'correctAnswer', 'explanation'],
                            'additionalProperties': False,
                        },
                    },
                },
                'required': ['quiz'],
                'additionalProperties': False,
            }
            resp = request_groq_completion(
                messages=[
                    {'role': 'system', 'content': 'Sen Türkçe çoktan seçmeli sınav hazırlayan bir API asistanısın. Yalnızca istenen JSON şemasına uygun çıktı ver.'},
                    {'role': 'user', 'content': prompt}
                ],
                response_format={
                    'type': 'json_schema',
                    'json_schema': {
                        'name': 'quiz_questions',
                        'strict': True,
                        'schema': quiz_schema,
                    },
                },
                temperature=0.3,
                max_completion_tokens=5000,
            )
            
            if resp.ok:
                if profile:
                    profile.ai_credits -= 1
                    profile.save()
                content = resp.json()['choices'][0]['message']['content']
                clean_content = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', content, flags=re.IGNORECASE).strip()
                if not clean_content.startswith(('[', '{')):
                    array_start = clean_content.find('[')
                    array_end = clean_content.rfind(']')
                    if array_start >= 0 and array_end > array_start:
                        clean_content = clean_content[array_start:array_end + 1]
                quiz_data = json.loads(clean_content)
                if isinstance(quiz_data, dict):
                    quiz_data = quiz_data.get('quiz', [])
                if not isinstance(quiz_data, list) or len(quiz_data) != count:
                    raise ValueError('Model beklenen sayıda soru döndürmedi.')
                return Response({'quiz': quiz_data})
            else:
                return Response({'error': 'Yapay zeka servisine ulaşılamadı.'}, status=400)
        except Exception as e:
            return Response({'error': 'Quiz oluşturulurken format hatası yaşandı. Lütfen tekrar deneyin.'}, status=500)


# --- 5. VERİTABANI: PROGRAM VE RAPORLAR ---
class ScheduleView(views.APIView):
    permission_classes = [permissions.IsAuthenticated] 

    def get(self, request):
        activity = UserActivity.objects.filter(
            user=request.user, 
            activity_type='schedule'
        ).order_by('-created_at').first() 
        
        if activity:
            stored_data = activity.data or {}
            schedule_value = stored_data.get('schedule', [])

            # Eski mobil sürüm tüm yapıyı schedule objesinin içinde saklamış olabilir.
            if isinstance(schedule_value, dict):
                return Response({
                    'plan': stored_data.get('plan') or schedule_value.get('plan'),
                    'pool': stored_data.get('pool') or schedule_value.get('pool', []),
                    'rows': stored_data.get('rows') or schedule_value.get('rows', []),
                })

            return Response({
                'plan': stored_data.get('plan'),
                'pool': stored_data.get('pool', []),
                'rows': stored_data.get('rows', schedule_value if isinstance(schedule_value, list) else []),
            })
        return Response({'plan': None, 'pool': [], 'rows': []})

    def post(self, request):
        schedule_value = request.data.get('schedule', [])
        nested_schedule = schedule_value if isinstance(schedule_value, dict) else {}
        plan = request.data.get('plan') or nested_schedule.get('plan')
        pool = request.data.get('pool') or nested_schedule.get('pool', [])
        rows = request.data.get('rows') or nested_schedule.get('rows')

        if rows is None:
            rows = schedule_value if isinstance(schedule_value, list) else []

        activity, created = UserActivity.objects.update_or_create(
            user=request.user,
            activity_type='schedule',
            defaults={
                'title': 'Haftalık Ders Programı',
                'data': {
                    'plan': plan,
                    'pool': pool,
                    'rows': rows,
                    'schedule': rows,
                }
            }
        )
        return Response({
            'message': 'Programın başarıyla kaydedildi!',
            'plan': plan,
            'pool': pool,
            'rows': rows,
        })

class DailyReportView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, date):
        activity = UserActivity.objects.filter(user=request.user, activity_type='daily_report', title=f"Rapor {date}").first()
        if activity:
            data = activity.data
            return Response({
                "dailyNotes": data.get("dailyNotes", data.get("report", "")),
                "productivityScore": data.get("productivityScore", data.get("productivity", 5)),
                "studyHours": data.get("studyHours", 0)
            })
        return Response({'dailyNotes': '', 'productivityScore': None, 'studyHours': None})

    def post(self, request):
        date = request.data.get('date')
        activity, created = UserActivity.objects.update_or_create(
            user=request.user,
            activity_type='daily_report',
            title=f"Rapor {date}",
            defaults={'data': request.data}
        )
        return Response({'message': 'Günlük rapor kaydedildi!'})

class AllReportsView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        activities = UserActivity.objects.filter(
            user=request.user, 
            activity_type='daily_report'
        ).order_by('-created_at')
        
        report_list = []
        for act in activities:
            report_data = dict(act.data) if act.data else {}
            if 'date' not in report_data:
                report_data['date'] = act.title.replace("Rapor ", "")
            report_list.append(report_data)
            
        return Response(report_list)


# --- 6. PDF DOSYA YÜKLEME VE ÖZETLEME ---
@method_decorator(csrf_exempt, name='dispatch')
class APIFileSummaryView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser] # Dosya kabul etmek için

    def post(self, request):
        profile = getattr(request.user, 'profile', None)
        if profile and profile.ai_credits <= 0:
            return Response({'error': 'Yapay zeka kullanım kotanız dolmuştur.'}, status=403)

        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'Lütfen bir dosya yükleyin.'}, status=400)

        # PDF İçeriğini Metne Çevirme
        text = ""
        try:
            if file_obj.name.endswith('.pdf'):
                doc = fitz.open(stream=file_obj.read(), filetype="pdf")
                for page in doc:
                    text += page.get_text()
            else:
                text = file_obj.read().decode('utf-8')
        except Exception as e:
            return Response({'error': 'Dosya okunamadı: ' + str(e)}, status=400)

        if len(text.strip()) < 10:
            return Response({'error': 'Dosya içeriği çok kısa veya metin bulunamadı.'}, status=400)

        # Mevcut AI Özetleme Mantığını Çağırıyoruz (Kod tekrarı yapmamak için senin sistemin)
        try:
            resp = request_groq_completion(
                messages=[
                    {'role': 'system', 'content': 'Sen bir ders asistanısın. Yüklenen PDF içeriğini en önemli başlıklarla özetle.'},
                    {'role': 'user', 'content': f"Şu PDF içeriğini özetle:\n\n{text[:10000]}"} # Çok uzunsa ilk 10k karakter
                ],
                temperature=0.3,
                max_completion_tokens=1800,
            )
            
            if resp.ok:
                if profile:
                    profile.ai_credits -= 1
                    profile.save()
                summary = resp.json()['choices'][0]['message']['content']
                return Response({'summary': summary})
            else:
                return Response({'error': 'AI servisi yanıt vermedi.'}, status=400)
        except Exception as e:
            return Response({'error': str(e)}, status=500)



# --- 7. GOOGLE TAKVİM ENTEGRASYONU ---

# --- 7. GOOGLE TAKVİM ENTEGRASYONU ---

def get_google_flow():
    client_config = {
        "web": {
            "client_id": os.environ.get('GOOGLE_CLIENT_ID'),
            "client_secret": os.environ.get('GOOGLE_CLIENT_SECRET'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["https://e-teacher.onrender.com/api/google/callback/"],
        }
    }
    
    flow = Flow.from_client_config(
        client_config,
        scopes=['https://www.googleapis.com/auth/calendar.events'],
        redirect_uri="https://e-teacher.onrender.com/api/google/callback/"
    )
    
    return flow

class GoogleCalendarInitView(views.APIView):
    permission_classes = [permissions.IsAuthenticated] 

    def get(self, request):
        flow = get_google_flow()
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        # B PLANI: Çerez (Session) yerine doğrudan sunucu belleğine kaydediyoruz!
        # Anahtar olarak Google'ın bize kaybetmeden geri getireceği 'state' kodunu kullanıyoruz.
        cache.set(state, {
            'code_verifier': flow.code_verifier,
            'user_id': request.user.id
        }, timeout=600) # 10 dakika boyunca sunucuda güvende kalacak
        
        return Response({'auth_url': authorization_url})


class GoogleCalendarCallbackView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        code = request.GET.get('code')
        state = request.GET.get('state') # Google'ın getirdiği bilet
        error = request.GET.get('error')

        if error or not code or not state:
            return Response({'error': 'Yetkilendirme hatası.'}, status=400)

        # B PLANI: Tarayıcıya sormuyoruz, bileti verip sunucumuzdan (Cache) şifreyi alıyoruz!
        saved_data = cache.get(state)

        if not saved_data:
            return Response({'error': 'Oturum zaman aşımı.'}, status=400)

        code_verifier = saved_data.get('code_verifier')
        user_id = saved_data.get('user_id')

        try:
            flow = get_google_flow()
            flow.code_verifier = code_verifier 
            flow.fetch_token(code=code)
            credentials = flow.credentials
            
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.get(id=user_id)

            GoogleCalendarCredential.objects.update_or_create(
                user=user,
                defaults={
                    'token': credentials.token,
                    'refresh_token': credentials.refresh_token,
                    'token_uri': credentials.token_uri,
                    'client_id': credentials.client_id,
                    'client_secret': credentials.client_secret,
                    'scopes': ",".join(credentials.scopes),
                }
            )
            
            # İşimiz bitince güvenliği sağlamak için şifreyi sunucudan siliyoruz
            cache.delete(state)
            
            return Response({'message': 'Harika! Takvim başarıyla hesabınıza bağlandı.'})
            
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class GoogleCalendarSyncView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            saved_credentials = request.user.calendar_credential
            credentials = Credentials(
                token=saved_credentials.token,
                refresh_token=saved_credentials.refresh_token,
                token_uri=saved_credentials.token_uri,
                client_id=saved_credentials.client_id,
                client_secret=saved_credentials.client_secret,
                scopes=saved_credentials.scopes.split(',')
            )

            if credentials.expired and credentials.refresh_token:
                credentials.refresh(GoogleAuthRequest())
                saved_credentials.token = credentials.token
                saved_credentials.save(update_fields=['token'])

            service = build('calendar', 'v3', credentials=credentials)
            calendar = service.calendars().get(calendarId='primary').execute()

            return Response({
                'message': 'Google Takvim bağlantısı doğrulandı.',
                'calendar_name': calendar.get('summary', 'Birincil Takvim')
            })
        except GoogleCalendarCredential.DoesNotExist:
            return Response(
                {'error': 'Google Takvim bağlı değil. Önce takvimi bağlayın.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as exc:
            return Response(
                {'error': f'Google Takvim bağlantısı doğrulanamadı: {str(exc)}'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        
# --- 8. GOOGLE MEET VE DERS OLUŞTURMA ---
class CreateLessonEventView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        
        # Frontend'den gelen veriler
        summary = request.data.get('summary', 'E-Teacher Canlı Etüt')
        description = request.data.get('description', 'E-Teacher platformu üzerinden otomatik oluşturulmuş ders.')
        start_time_raw = request.data.get('start_time')
        end_time_raw = request.data.get('end_time')
        is_recurring = request.data.get('is_recurring', False)

        if not start_time_raw or not end_time_raw:
            return Response({'error': 'Başlangıç ve bitiş zamanı zorunludur.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # --- 1. AŞAMA: GOOGLE API İLE TAKVİM VE MEET OLUŞTURMA ---
            creds_data = user.calendar_credential
            
            credentials = Credentials(
                token=creds_data.token,
                refresh_token=creds_data.refresh_token,
                token_uri=creds_data.token_uri,
                client_id=creds_data.client_id,
                client_secret=creds_data.client_secret,
                scopes=creds_data.scopes.split(',')
            )

            service = build('calendar', 'v3', credentials=credentials)

            event_details = {
                'summary': summary,
                'description': description,
                'start': {'dateTime': f"{start_time_raw}:00+03:00", 'timeZone': 'Europe/Istanbul'},
                'end': {'dateTime': f"{end_time_raw}:00+03:00", 'timeZone': 'Europe/Istanbul'},
                'conferenceData': {
                    'createRequest': {'requestId': str(uuid.uuid4()), 'conferenceSolutionKey': {'type': 'hangoutsMeet'}}
                }
            }

            if is_recurring:
                event_details['recurrence'] = ['RRULE:FREQ=WEEKLY']

            event = service.events().insert(
                calendarId='primary', 
                body=event_details, 
                conferenceDataVersion=1
            ).execute()

            # --- 2. AŞAMA: ALINAN BİLGİLERİ KENDİ VERİTABANIMIZA (NEON) KAYDETME ---
            new_lesson = Lesson.objects.create(
                teacher=user,
                title=summary,
                description=description,
                start_time=f"{start_time_raw}:00+03:00", # Django saati net anlasın diye formatlandı
                end_time=f"{end_time_raw}:00+03:00",
                google_event_id=event.get('id'),
                meet_link=event.get('hangoutLink'),
                is_recurring=is_recurring
            )

            # İşlem başarılıysa Frontend'e dönecek yanıt
            return Response({
                'message': 'Ders başarıyla planlandı ve veritabanına kaydedildi!',
                'meet_link': new_lesson.meet_link,
                'event_link': event.get('htmlLink'),
                'summary': new_lesson.title,
            })

        except GoogleCalendarCredential.DoesNotExist:
            return Response({'error': 'Takvim bağlı değil. Önce profilinizden takvimi bağlayın.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Sistem Hatası: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class LessonListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LessonSerializer

    def get_queryset(self):
        # Şimdilik sistemdeki tüm dersleri tarihe göre sıralayıp getiriyoruz.
        # İleride buraya "Sadece kullanıcının (öğrencinin) kayıtlı olduğu dersleri getir" filtresi ekleyeceğiz.
        return Lesson.objects.all().order_by('start_time')
# DİKKAT: CreateAdminView SINIFINI TAMAMEN SİLDİK! 
