import csv
import os
import tkinter as tk
from tkinter import messagebox

CSV_FILE = "tripflow_data.csv"


def create_csv_if_not_exists():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow([
                "出張名", "開始日", "終了日", "目的地",
                "ホテル", "往路交通", "復路交通",
                "金額", "予約リンク", "メモ"
            ])


def save_trip():
    trip_name = entry_trip_name.get()
    start_date = entry_start_date.get()
    end_date = entry_end_date.get()
    destination = entry_destination.get()
    hotel = hotel_var.get()
    outbound = outbound_var.get()
    return_trip = return_var.get()
    amount = entry_amount.get()
    link = entry_link.get()
    memo = entry_memo.get()

    if trip_name == "" or destination == "":
        messagebox.showwarning("入力エラー", "出張名と目的地は入力してください。")
        return

    with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            trip_name, start_date, end_date, destination,
            hotel, outbound, return_trip, amount, link, memo
        ])

    messagebox.showinfo("保存完了", "出張予定を保存しました！")
    clear_entries()
    load_trips()


def clear_entries():
    entry_trip_name.delete(0, tk.END)
    entry_start_date.delete(0, tk.END)
    entry_end_date.delete(0, tk.END)
    entry_destination.delete(0, tk.END)
    entry_amount.delete(0, tk.END)
    entry_link.delete(0, tk.END)
    entry_memo.delete(0, tk.END)


def load_trips():
    listbox.delete(0, tk.END)

    if not os.path.exists(CSV_FILE):
        return

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        count = 0

        for row in reader:
            count += 1
            status = "✅予約OK"

            if row["ホテル"] == "未" or row["往路交通"] == "未" or row["復路交通"] == "未":
                status = "⚠️未予約あり"

            display_text = (
                f"{status}｜{row['出張名']}｜{row['開始日']}〜{row['終了日']}｜"
                f"{row['目的地']}｜{row['金額']}円"
            )

            listbox.insert(tk.END, display_text)

    count_label.config(text=f"登録済み出張：{count}件")


create_csv_if_not_exists()

root = tk.Tk()
root.title("TripFlow v0.2")
root.geometry("750x750")

title_label = tk.Label(root, text="🚄 TripFlow", font=("Arial", 22, "bold"))
title_label.pack(pady=10)

subtitle_label = tk.Label(root, text="出張予定・交通・ホテル・費用を一元管理", font=("Arial", 11))
subtitle_label.pack(pady=5)

frame = tk.Frame(root)
frame.pack(pady=10)

tk.Label(frame, text="出張名").grid(row=0, column=0, sticky="w", pady=5)
entry_trip_name = tk.Entry(frame, width=45)
entry_trip_name.grid(row=0, column=1, pady=5)

tk.Label(frame, text="開始日").grid(row=1, column=0, sticky="w", pady=5)
entry_start_date = tk.Entry(frame, width=45)
entry_start_date.grid(row=1, column=1, pady=5)

tk.Label(frame, text="終了日").grid(row=2, column=0, sticky="w", pady=5)
entry_end_date = tk.Entry(frame, width=45)
entry_end_date.grid(row=2, column=1, pady=5)

tk.Label(frame, text="目的地").grid(row=3, column=0, sticky="w", pady=5)
entry_destination = tk.Entry(frame, width=45)
entry_destination.grid(row=3, column=1, pady=5)

hotel_var = tk.StringVar(value="未")
outbound_var = tk.StringVar(value="未")
return_var = tk.StringVar(value="未")

tk.Label(frame, text="ホテル").grid(row=4, column=0, sticky="w", pady=5)
tk.OptionMenu(frame, hotel_var, "済", "未").grid(row=4, column=1, sticky="w", pady=5)

tk.Label(frame, text="往路交通").grid(row=5, column=0, sticky="w", pady=5)
tk.OptionMenu(frame, outbound_var, "済", "未").grid(row=5, column=1, sticky="w", pady=5)

tk.Label(frame, text="復路交通").grid(row=6, column=0, sticky="w", pady=5)
tk.OptionMenu(frame, return_var, "済", "未").grid(row=6, column=1, sticky="w", pady=5)

tk.Label(frame, text="金額").grid(row=7, column=0, sticky="w", pady=5)
entry_amount = tk.Entry(frame, width=45)
entry_amount.grid(row=7, column=1, pady=5)

tk.Label(frame, text="予約リンク").grid(row=8, column=0, sticky="w", pady=5)
entry_link = tk.Entry(frame, width=45)
entry_link.grid(row=8, column=1, pady=5)

tk.Label(frame, text="メモ").grid(row=9, column=0, sticky="w", pady=5)
entry_memo = tk.Entry(frame, width=45)
entry_memo.grid(row=9, column=1, pady=5)

save_button = tk.Button(root, text="保存する", command=save_trip, width=20, height=2)
save_button.pack(pady=15)

count_label = tk.Label(root, text="登録済み出張：0件", font=("Arial", 11, "bold"))
count_label.pack(pady=5)

listbox = tk.Listbox(root, width=100, height=12)
listbox.pack(pady=10)

reload_button = tk.Button(root, text="一覧を更新", command=load_trips, width=20)
reload_button.pack(pady=5)

load_trips()

root.mainloop()