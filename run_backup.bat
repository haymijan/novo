@echo off

:: --- নিচের পাথগুলো আপনার প্রজেক্ট অনুযায়ী পরিবর্তন করুন ---

:: আপনার প্রজেক্টের ফোল্ডারের পাথ
cd "C:\Users\Admin\Desktop\inventory_project"

:: --- মূল পরিবর্তন: সরাসরি venv-এর পাইথন ব্যবহার করা হচ্ছে ---
echo Running backup command using virtual environment...

:: venv/Scripts ফোল্ডারের ভেতরে থাকা python.exe-কে সরাসরি কল করা হচ্ছে
"C:\Users\Admin\Desktop\inventory_project\venv\Scripts\python.exe" manage.py backup

echo Backup process finished.

pause