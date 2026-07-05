print("🔥 Project Phoenix")
print("-------------------------")
print("昨日の自分より1%前へ。")
print()

python_goal = 100

python_hours = int(input("Python学習時間を入力してください："))
note_count = input("noteの記事数を入力してください：")
students = input("家庭教師の生徒数を入力してください：")
debt = input("借入残高を入力してください：")

progress = python_hours / python_goal * 100

if python_hours >= 100:
    level = 5
elif python_hours >= 50:
    level = 4
elif python_hours >= 20:
    level = 3
elif python_hours >= 10:
    level = 2
else:
    level = 1

print()
print("===== 今日の進捗 =====")
print(f"🏅 Project Phoenix Lv.{level}")
print(f"Python：{python_hours}時間")
print(f"Python進捗：{progress:.1f}%")
print(f"note：{note_count}記事")
print(f"家庭教師：{students}名")
print(f"借入：{debt}円")
print()

if progress >= 100:
    print("🎉 Python目標達成！！")
else:
    print("まだまだ積み上げよう🔥")

print()
print("🏆 今日の目標")
print("□ Python")
print("□ note")
print("□ GitHub")
print("□ X")