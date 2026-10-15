# Audit Report - Class 7 Section A vs FEMIS Portal

- **Date:** 2026-10-15 21:24
- **Scope:** every local student with class_id=7, section_id=A
- **Method:** portal student list scraped at 100 records/page (read-only), then each match verified on its record detail page by **name, B-Form/CNIC, father CNIC, class and section**
- **Local entries audited:** 60
- **Portal list rows scanned:** 739 (headers: #, Name, B-Form / Student ID, Gender, Class, School, Status, Actions)

## Summary

| Verdict | Count | Meaning |
|---|---:|---|
| OK | 51 | VERIFIED - name + CNIC + class + section all match |
| CNIC-NOT-ON-PORTAL | 1 | on portal by name/class/section but portal holds no CNIC (TMP id) |
| NAME-DIFF | 7 | found by CNIC but portal NAME differs |
| CNIC-DIFF | 1 | found by name but B-Form/CNIC differs |
| **TOTAL** | **60** | |

## Per-student results

| Roll | Local name | Local B-Form | Portal name | Portal B-Form / ID | Father CNIC match | Class | Section | Verdict | Notes |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | Eman Riaz | 61101-7943502-0 | EMAN RIAZ | 6110179435020 | yes | Class 7 | A | **OK** |  |
| 2 | Zohra Wazir | 11102-0619165-0 | ZOHRA WAZIR | 1110206191650 | yes | Class 7 | A | **OK** |  |
| 3 | Misbah Ejaz | 61101-6855089-6 | MISBHA IJAZ | 6110168550896 | yes | Class 7 | A | **NAME-DIFF** | portal name='MISBHA IJAZ' |
| 4 | Sunaina Batool | 21303-9289497-4 | SUNAINA BATOOL | 2130392894974 | yes | Class 7 | A | **OK** |  |
| 5 | Mahnoor Shakeel | 37405-9567138-0 | MAHNOOR SHAKEEL | 3740595671380 | yes | Class 7 | A | **OK** |  |
| 6 | Zainab Ali | 61101-9256974-6 | ZAINAB ALI | 6110192569746 | yes | Class 7 | A | **OK** |  |
| 7 | Hadia Iqbal | 61101-7439115-2 | HADIA IQBAL | 6110174391152 | n/a | ? | ? | **OK** | detail read failed |
| 8 | Habiba Bibi | 16103-0594659-0 | HABIBA BIBI | 1610305946590 | n/a | ? | ? | **OK** | detail read failed |
| 9 | Hooria Jabeen | 37405-5227563-8 | HOORIYA JABEEN | 3740552275638 | n/a | ? | ? | **NAME-DIFF** | detail read failed; portal name='HOORIYA JABEEN' |
| 10 | Alisha Zulfiqar | 37405-2134504-4 | ALISHA ZULFIQAR | 3740521345044 | n/a | ? | ? | **OK** | detail read failed |
| 11 | Esha Anmol | 61101-3495756-8 | ESHA ANMOL | 6110134957568 | n/a | ? | ? | **OK** | detail read failed |
| 12 | Zunaira kamran | 12101-4222300-0 | ZUNAIRA KAMRAN | 1210142223000 | n/a | ? | ? | **OK** | detail read failed |
| 13 | Syeda Noor ul Ain | 71105-0581590-4 | SYEDA NOOR UL AIN | 7110505815904 | n/a | ? | ? | **OK** | detail read failed |
| 14 | Fatima Shahzadi | 37405-0333383-0 | FATIMA SHEHZADI | 3740503333830 | n/a | ? | ? | **NAME-DIFF** | detail read failed; portal name='FATIMA SHEHZADI' |
| 15 | Summia Shafiq | 11101-1965076-4 | SUMMIA | 1110119650764 | yes | Class 7 | A | **NAME-DIFF** | portal name='SUMMIA' |
| 16 | Hamna Tufail | 37405-6834776-4 | HAMNA TUFAIL | 3740568347764 | yes | Class 7 | A | **OK** |  |
| 17 | Ayesha Jahangir | 61101-9368915-6 | AYESHA JAHANGIR | 6110193689156 | yes | Class 7 | A | **OK** |  |
| 18 | Iqra Hashmi | 61101-1782732-2 | IQRA HASHMI | 6110117827322 | yes | Class 7 | A | **OK** |  |
| 19 | khadija Zahra | 61101-4628596-0 | KHADIJA ZAHRA | 6110146285960 | yes | Class 7 | A | **OK** |  |
| 20 | Maryam Amir | 37405-2691855-8 | MARYAM AAMIR | 3740526918558 | yes | Class 7 | A | **NAME-DIFF** | portal name='MARYAM AAMIR' |
| 21 | Isra Abid | 37405-7349462-8 | ISRA ABID | 3740573494628 | yes | Class 7 | A | **OK** |  |
| 22 | Sahar Almas | 11201-3714463-4 | SAHAR ALMAS SALEEM | 1120137144634 | yes | Class 7 | A | **NAME-DIFF** | portal name='SAHAR ALMAS SALEEM' |
| 23 | Roha pari | 37405-2868121-6 | ROHA PARI | 3740528681216 | yes | Class 7 | A | **OK** |  |
| 24 | Summiya Noor | 21105-3108568-6 | SUMMIYA NOOR | TMP-2026-36033 | yes | Class 7 | A | **CNIC-NOT-ON-PORTAL** | portal B-Form='TMP-2026-36033' (TMP - no CNIC by design) |
| 25 | Areeqa Zahra | 37405-8080028-8 | AREEQA ZAHRA | 3740580800288 | n/a | ? | ? | **OK** | detail read failed |
| 26 | Nimra Shabbir | 37405-9318285-6 | NIMRA SHABBIR | 3740593182856 | n/a | ? | ? | **OK** | detail read failed |
| 27 | Ammara Ehsan | 38403-8072724-3 | AMMARA EHSAN | 3840380727243 | n/a | ? | ? | **OK** | detail read failed |
| 28 | khadija Akhlaq | 37102-6368639-4 | KHADIJA AKHLAQ | 3710263686394 | n/a | ? | ? | **OK** | detail read failed |
| 29 | Tanzeela Bibi | 37405-1916816-0 | TANZEELA BIBI | 3740519168160 | n/a | ? | ? | **OK** | detail read failed |
| 30 | Mehak Fatima | 37402-4578447-4 | MEHAK FATIMA | 3740570972226 | n/a | ? | ? | **CNIC-DIFF** | detail read failed; portal B-Form='3740570972226' |
| 31 | Jannat Noor | 61101-4294475-4 | JANNAT NOOR | 6110142944754 | n/a | ? | ? | **OK** | detail read failed |
| 32 | Hurain Sajid | 37405-3077609-0 | HURAIN SAJID | 3740530776090 | n/a | ? | ? | **OK** | detail read failed |
| 33 | Amna Bibi | 61101-1398442-2 | AMNA BIBI | 6110113984422 | n/a | ? | ? | **OK** | detail read failed |
| 34 | Kinza Hayat | 37405-9203525-6 | KINZA HAYAT | 3740592035256 | n/a | ? | ? | **OK** | detail read failed |
| 35 | Shumaim Shahzadi | 37405-2110818-2 | SHUMAIM SHAHZADI | 3740521108182 | n/a | ? | ? | **OK** | detail read failed |
| 36 | Maheera Amjad | 37405-7976705-8 | MAHEERA AMJAD | 3740579767058 | n/a | ? | ? | **OK** | detail read failed |
| 37 | Fatima Noor | 61101-8928656-4 | FATIMA NOOR | 6110189286564 | n/a | ? | ? | **OK** | detail read failed |
| 38 | Hajra Riaz | 61101-5492968-6 | HAJRA RIAZ | 6110154929686 | n/a | ? | ? | **OK** | detail read failed |
| 39 | Maria Bibi | 61101-1720099-4 | MARIA BIBI | 6110117200994 | n/a | ? | ? | **OK** | detail read failed |
| 40 | Ayesha Alam | 61101-1907153-8 | AISHA ALAM | 6110119071538 | n/a | ? | ? | **NAME-DIFF** | detail read failed; portal name='AISHA ALAM' |
| 41 | Zaina Fahad | 37405-9566209-1 | ZAINA FAHAD | 3740595662091 | n/a | ? | ? | **OK** | detail read failed |
| 42 | Zainab Fatima | 37405-8524197-6 | ZAINAB FATIMA | 3740585241976 | n/a | ? | ? | **OK** | detail read failed |
| 43 | Aleena Arshad | 37405-7441551-8 | ALEENA ARSHAD | 3740574415518 | n/a | ? | ? | **OK** | detail read failed |
| 44 | Zara Munir | 37405-1885977-0 | ZARA MUNIR | 3740518859770 | n/a | ? | ? | **OK** | detail read failed |
| 45 | Raima Shakeel | 37405-0460664-1 | RAIMA SHAKEEL | 3740504606641 | n/a | ? | ? | **OK** | detail read failed |
| 46 | Eshaal Irfan | 61101-0561915-6 | ESHAAL IRFAN | 6110105619156 | n/a | ? | ? | **OK** | detail read failed |
| 47 | Harain Zahra | 61101-4537032-7 | HARAIN ZAHRA | 6110145370327 | n/a | ? | ? | **OK** | detail read failed |
| 48 | Seerat Bibi | 13101-3469451-2 | SEERAT BIBI | 1310134694512 | n/a | ? | ? | **OK** | detail read failed |
| 49 | Manahil Nadeem | 61101-8292326-2 | MANAHIL NADEEM | 6110182923262 | n/a | ? | ? | **OK** | detail read failed |
| 50 | Manahil Rehman | 37405-1221577-4 | MANAHIL REHMAN | 3740512215774 | n/a | ? | ? | **OK** | detail read failed |
| 51 | Uzma Batool | 61101-8125195-8 | UZMA BATOOL | 6110181251958 | n/a | ? | ? | **OK** | detail read failed |
| 52 | Wania Batool | 37405-2260443-0 | WANIA BATOOL | 3740522604430 | n/a | ? | ? | **OK** | detail read failed |
| 53 | Ammarah Binte jawad | 61101-7778228-8 | AMMARAH BINTE JAWAD | 6110177782288 | n/a | ? | ? | **OK** | detail read failed |
| 54 | Wajiha | 61101-6459401-6 | WAJIHA | 6110164594016 | n/a | ? | ? | **OK** | detail read failed |
| 55 | Hoor E Aina | 61101-4783250-8 | HOOR E AINA | 6110147832508 | n/a | ? | ? | **OK** | detail read failed |
| 56 | Abeera kamran | 37405-8631082-4 | ABEERA KAMRAN | 3740586310824 | n/a | ? | ? | **OK** | detail read failed |
| 57 | Shafia Batool | 38407-0400385-4 | SHAFIA BATOOL | 3840704003854 | n/a | ? | ? | **OK** | detail read failed |
| 58 | Malik Fatima Awan | 13101-6072384-6 | MALIK FATIMA AWAN | 1310160723846 | n/a | ? | ? | **OK** | detail read failed |
| 59 | khadija Haroon | 17301-9743599-2 | KHADIJA HAROON | 1730197435992 | n/a | ? | ? | **OK** | detail read failed |
| 60 | Midhat Fatima | 41306-9079344-8 | MIDHAT FATIMA | 4130690793448 | n/a | ? | ? | **OK** | detail read failed |

## Method notes

- Match precedence: exact (name + CNIC) > name > CNIC > missing.
- Name comparison is case- and whitespace-insensitive.
- CNIC comparison strips dashes/spaces (13-digit compare); portal TMP- ids carry no CNIC, so CNIC is not applicable for them.
- Detail pages were opened read-only; nothing was saved.
- Local DB was not modified by this audit.
