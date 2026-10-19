//+------------------------------------------------------------------+
//| PMW_ExtIndicatorExporter.mq5 - PepeMarketWizard (PMW-UPD-02)      |
//| Read-only exporter of chart OBJECTS created by a licensed         |
//| indicator (IQ Gold Gann / IQ Star Lines / identified PAL02M).     |
//| - custom indicator: no trading functions, does not occupy the EA  |
//|   slot, never changes objects, scale or inputs of the source;     |
//| - inventory of objects whose name starts with InpPrefix (or all   |
//|   when empty, bounded by InpMaxObjects) -> envelope pmw-extind-1; |
//| - body text SHA-256 (CryptEncode), tmp file + FileMove (atomic)   |
//|   in the COMMON files folder: Common\Files\PMW_extind\            |
//| Times are broker SERVER time (time_basis=BROKER_SERVER); the bot  |
//| converts them with its verified clock offset (or marks            |
//| TIME_BASIS_UNVERIFIED). Compile in MetaEditor (not done in the    |
//| build environment: NOT_COMPILED_NO_METAEDITOR).                   |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_plots 0
#property version   "1.00"

input string InpAdapterId    = "IQ_GOLD_GANN";   // IQ_GOLD_GANN | IQ_STAR_LINES | PAL02M
input string InpPrefix       = "";               // object name prefix of the SOURCE indicator (empty = inventory of all)
input string InpProductVer   = "";               // installed product version (as shown in Navigator/Market)
input int    InpTimerSeconds = 2;
input int    InpMaxObjects   = 500;

long   g_generation = 0;
long   g_sequence   = 0;
string g_lastBody   = "";

string JsonEsc(const string s)
  {
   string r = s;
   StringReplace(r, "\\", "\\\\");
   StringReplace(r, "\"", "\\\"");
   StringReplace(r, "\n", "\\n");
   StringReplace(r, "\r", "\\r");
   StringReplace(r, "\t", "\\t");
   return r;
  }

string Num(const double v)
  {
   if(v == EMPTY_VALUE || !MathIsValidNumber(v)) return "null";
   return DoubleToString(v, 10);
  }

string TypeName(const ENUM_OBJECT t)
  {
   switch(t)
     {
      case OBJ_HLINE:     return "HLINE";
      case OBJ_TREND:     return "TREND";
      case OBJ_VLINE:     return "VLINE";
      case OBJ_RECTANGLE: return "RECTANGLE";
      case OBJ_FIBO:      return "FIBO";
      case OBJ_TEXT:      return "TEXT";
      case OBJ_LABEL:     return "LABEL";
     }
   return "OTHER";
  }

string Sha256Hex(const string text)
  {
   uchar data[], key[], res[];
   StringToCharArray(text, data, 0, StringLen(text), CP_UTF8);
   if(CryptEncode(CRYPT_HASH_SHA256, data, key, res) <= 0) return "";
   string hex = "";
   for(int i = 0; i < ArraySize(res); i++) hex += StringFormat("%02x", res[i]);
   return hex;
  }

string ObjectsJson(const long chart, int &count)
  {
   string out = "[";
   count = 0;
   int total = ObjectsTotal(chart, -1, -1);
   for(int i = 0; i < total && count < InpMaxObjects; i++)
     {
      string name = ObjectName(chart, i, -1, -1);
      if(InpPrefix != "" && StringFind(name, InpPrefix) != 0) continue;
      ENUM_OBJECT t = (ENUM_OBJECT)ObjectGetInteger(chart, name, OBJPROP_TYPE);
      string tn = TypeName(t);
      int pts = (t == OBJ_TREND || t == OBJ_RECTANGLE || t == OBJ_FIBO) ? 2 : 1;
      string prices = "[", times = "[";
      for(int k = 0; k < pts; k++)
        {
         if(k > 0) { prices += ","; times += ","; }
         prices += Num(ObjectGetDouble(chart, name, OBJPROP_PRICE, k));
         times  += IntegerToString((long)ObjectGetInteger(chart, name, OBJPROP_TIME, k));
        }
      prices += "]"; times += "]";
      if(t == OBJ_HLINE) times = "[]";
      if(t == OBJ_VLINE) prices = "[]";
      if(count > 0) out += ",";
      out += "{\"name\":\"" + JsonEsc(name) + "\",\"type\":\"" + tn + "\",\"prices\":" + prices + ",\"times\":" + times +
             ",\"text\":\"" + JsonEsc(ObjectGetString(chart, name, OBJPROP_TEXT)) + "\",\"color\":" +
             IntegerToString((long)ObjectGetInteger(chart, name, OBJPROP_COLOR)) + "}";
      count++;
     }
   return out + "]";
  }

void Export()
  {
   long chart = ChartID();
   int n = 0;
   string objs = ObjectsJson(chart, n);
   string fp = AccountInfoString(ACCOUNT_SERVER) + ":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN) % 1000);   // short, no full login
   string core = objs + "|" + _Symbol + "|" + EnumToString(_Period);
   if(core != g_lastBody) { g_generation++; g_lastBody = core; }
   g_sequence++;
   string body = "{\"schema_version\":\"pmw-extind-1\",\"producer_version\":\"PMW_ExtIndicatorExporter/1.00\",\"adapter_id\":\"" +
                 JsonEsc(InpAdapterId) + "\",\"product\":{\"version\":\"" + JsonEsc(InpProductVer) + "\"},\"terminal_fingerprint\":\"" +
                 JsonEsc(fp) + "\",\"chart_id\":\"" + IntegerToString(chart) + "\",\"symbol\":\"" + JsonEsc(_Symbol) + "\",\"tf\":\"" +
                 EnumToString(_Period) + "\",\"time_basis\":\"BROKER_SERVER\",\"captured_at_server\":" + IntegerToString((long)TimeCurrent()) +
                 ",\"captured_at_gmt\":" + IntegerToString((long)TimeGMT()) + ",\"generation\":" + IntegerToString(g_generation) +
                 ",\"sequence\":" + IntegerToString(g_sequence) + ",\"complete\":true,\"objects\":" + objs + "}";
   string outer = "{\"envelope\":\"pmw-extind-1\",\"checksum\":\"" + Sha256Hex(body) + "\",\"body\":\"" + JsonEsc(body) + "\"}";
   string dir = "PMW_extind\\";
   string fn = dir + InpAdapterId + "__" + IntegerToString(chart) + ".json";
   string tmp = fn + ".tmp";
   int h = FileOpen(tmp, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON, 0, CP_UTF8);
   if(h == INVALID_HANDLE) { Print("PMW exporter: FileOpen failed ", GetLastError()); return; }
   FileWriteString(h, outer);
   FileClose(h);
   if(!FileMove(tmp, FILE_COMMON, fn, FILE_COMMON | FILE_REWRITE))
      Print("PMW exporter: FileMove failed ", GetLastError());
  }

int OnInit()
  {
   EventSetTimer(MathMax(1, InpTimerSeconds));
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer() { Export(); }

int OnCalculate(const int rates_total, const int prev_calculated, const int begin, const double &price[])
  {
   return(rates_total);
  }
