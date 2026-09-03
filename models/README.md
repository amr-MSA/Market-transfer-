# نموذج MediaPipe Pose (فلتر الوضعية)

هذا المجلد يجب أن يحتوي `pose_landmarker_lite.task` (~5.5 ميجابايت) — نموذج MediaPipe Pose
Landmarker المستخدم في `bot/media.py` لرفض أي صورة يظهر فيها الورك/الركبة/الكاحل قبل عرضها
للمراجعة الإدارية (راجع قسم "فلتر الوضعية" في README الرئيسي).

هذا الملف **لا يأتي مضمّنًا** مع حزمة `mediapipe` على PyPI، ولا يمكن تنزيله تلقائيًا من بيئة
بلا اتصال بالإنترنت. نزّله مرة واحدة يدويًا وارفعه هنا:

```bash
curl -L -o models/pose_landmarker_lite.task \
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
```

أو عبر `wget`:

```bash
wget -O models/pose_landmarker_lite.task \
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
```

بعدها ارفعه إلى GitHub بأمر عادي (لا يحتاج Git LFS؛ حجمه أقل بكثير من حد الـ 100 ميجابايت):

```bash
git add models/pose_landmarker_lite.task
git commit -m "chore: bundle pose landmarker model"
git push
```

## ماذا لو لم يُرفع الملف؟

الكود لا يتعطل — `bot/media.py` يحاول بالترتيب: (1) هذا المسار المضمّن في المستودع،
(2) نسخة محفوظة مسبقًا في ذاكرة تخزين مؤقت محلية، (3) تنزيل مباشر من خوادم Google كحل أخير.
فشل الخطوات الثلاث معًا يُعطِّل فلتر الوضعية تلقائيًا لبقية التشغيل بدل أن يمنع كل الصور —
لكن الأسلم والأضمن هو رفع الملف هنا مرة واحدة وعدم الاعتماد على الشبكة إطلاقًا.
