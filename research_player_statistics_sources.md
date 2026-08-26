# مرجع ربط إحصاءات الموسم

تمت مراجعة توثيق API-Football الرسمي في 2026-08-26 قبل بناء `bot/player_statistics.py`.

| الموضوع | النتيجة المرجعية | المصدر |
|---|---|---|
| العنوان | `https://v3.football.api-sports.io` هو عنوان واجهة الخدمة، وليس مفتاح API. | https://www.api-football.com/documentation-v3 |
| المصادقة | جميع الطلبات تستخدم رأس `x-apisports-key` بمفتاح المستخدم. | https://www.api-football.com/documentation-v3 |
| حالة الحصة | المسار `GET /status` يعرض الاستهلاك ولا يحتسب ضمن الحصة اليومية. | https://www.api-football.com/documentation-v3 |
| اللاعب/الموسم | `GET /players?id={id}&season={YYYY}` يعيد بيانات اللاعب وإحصاءاته، ويشترط الموسم مع اللاعب أو النادي أو الدوري. | https://www.api-football.com/documentation-v3 |
| الحقول | الاستجابة تشمل المباريات والدقائق والمركز والأهداف والصناعات والتمريرات المفتاحية والتدخلات والاعتراضات والإبعادات والأهداف المستقبلة والتصديات. | https://www.api-football.com/documentation-v3 |
| المحافظة على الحصة | التوثيق يوصي باستدعاء إحصاءات اللاعب على فواصل أسبوعية؛ هذا المشروع يزيد الحماية بتخزين مؤقت 30 يومًا للبطاقات المرجعية للموسم السابق. | https://www.api-football.com/documentation-v3 |

لا تُعرض أي إحصاءات قبل وجود `API_FOOTBALL_KEY` في الأسرار، ولا يقبل الربط لاعبًا أو ناديًا إلا عند تطابق الاسم بدقة.
