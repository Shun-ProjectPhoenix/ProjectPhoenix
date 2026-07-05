import csv
import os
import tkinter as tk
from tkinter import messagebox

CSV_FILE = "TripFlow/data/tripflow_data.csv"

selected_index = None


def create_csv_if_not_exists():
    os.makedirs("TripFlow/data", exist_ok=True)

    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow([
                "出張名", "開始日", "終了日", "目的地",
                "ホテル", "往路交通", "復路交通",
                "金額", "予約リンク", "メモ"
            ])


def read_trips():
    trips = []

    if not os.path.exists(CSV_FILE):
        return trips

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            trips.append(row)

    return trips


def write_trips(trips):
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as file:
        fieldnames = [
            "出張名", "開始日", "終了日", "目的地",
            "ホテル", "往路交通", "復路交通",
            "金額", "予約リンク", "メモ"
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trips)


def clear_entries():
    global selected_index

    entry_trip_name.delete(0, tk.END)
    entry_start_date.delete(0, tk.END)
    entry_end_date.delete(0, tk.END)
    entry_destination.delete(0, tk.END)
    entry_amount.delete(0, tk.END)
    entry_link.delete(0, tk.END)
    entry_memo.delete(0, tk.END)

    hotel_var.set("未")
    outbound_var.set("未")
    return_var.set("未")

    selected_index = None


def get_form_data():
    return {
        "出張名": entry_trip_name.get(),
        "開始日": entry_start_date.get(),
        "終了日": entry_end_date.get(),
        "目的地": entry_destination.get(),
        "ホテル": hotel_var.get(),
        "往路交通": outbound_var.get(),
        "復路交通": return_var.get(),
        "金額": entry_amount.get(),
        "予約リンク": entry_link.get(),
        "メモ": entry_memo.get()
    }


def save_trip():
    trip = get_form_data()

    if trip["出張名"] == "" or trip["目的地"] == "":
        messagebox.showwarning("入力エラー", "出張名と目的地は入力してください。")
        return

    trips = read_trips()
    trips.append(trip)
    write_trips(trips)

    messagebox.showinfo("保存完了", "出張予定を保存しました！")
    clear_entries()
    load_trips()


def update_trip():
    global selected_index

    if selected_index is None:
        messagebox.showwarning("選択エラー", "更新する出張を一覧から選択してください。")
        return

    trip = get_form_data()

    if trip["出張名"] == "" or trip["目的地"] == "":
        messagebox.showwarning("入力エラー", "出張名と目的地は入力してください。")
        return

    trips = read_trips()
    trips[selected_index] = trip
    write_trips(trips)

    messagebox.showinfo("更新完了", "出張予定を更新しました！")
    clear_entries()
    load_trips()


def delete_trip():
    global selected_index

    if selected_index is None:
        messagebox.showwarning("選択エラー", "削除する出張を一覧から選択してください。")
        return

    result = messagebox.askyesno("削除確認", "選択した出張予定を削除しますか？")

    if result:
        trips = read_trips()
        del trips[selected_index]
        write_trips(trips)

        messagebox.showinfo("削除完了", "出張予定を削除しました。")
        clear_entries()
        load_trips()


def load_trips():
    listbox.delete(0, tk.END)

    trips = read_trips()

    for trip in trips:
        status = "✅予約OK"

        if trip["ホテル"] == "未" or trip["往路交通"] == "未" or trip["復路交通"] == "未":
            status = "⚠️未予約あり"

        display_text = (
            f"{status}｜{trip['出張名']}｜{trip['開始日']}〜{trip['終了日']}｜"
            f"{trip['目的地']}｜{trip['金額']}円"
        )

        listbox.insert(tk.END, display_text)

    count_label.config(text=f"登録済み出張：{len(trips)}件")


def select_trip(event):
    global selected_index

    selected = listbox.curselection()

    if not selected:
        return

    selected_index = selected[0]
    trips = read_trips()
    trip = trips[selected_index]

    clear_entries()
    selected_index = selected[0]

    entry_trip_name.insert(0, trip["出張名"])
    entry_start_date.insert(0, trip["開始日"])
    entry_end_date.insert(0, trip["終了日"])
    entry_destination.insert(0, trip["目的地"])
    hotel_var.set(trip["ホテル"])
    outbound_var.set(trip["往路交通"])
    return_var.set(trip["復路交通"])
    entry_amount.insert(0, trip["金額"])
    entry_link.insert(0, trip["予約リンク"])
    entry_memo.insert(0, trip["メモ"])


create_csv_if_not_exists()

root = tk.Tk()
root.title("TripFlow v0.3")
root.geometry("850x750")

title_label = tk.Label(root, text="🚄 TripFlow", font=("Arial", 22, "bold"))
title_label.pack(pady=10)

subtitle_label = tk.Label(root, text="出張予定・交通・ホテル・費用を一元管理", font=("Arial", 11))
subtitle_label.pack(pady=5)

frame = tk.Frame(root)
frame.pack(pady=10)

tk.Label(frame, text="出張名").grid(row=0, column=0, sticky="w", pady=5)
entry_trip_name = tk.Entry(frame, width=50)
entry_trip_name.grid(row=0, column=1, pady=5)

tk.Label(frame, text="開始日").grid(row=1, column=0, sticky="w", pady=5)
entry_start_date = tk.Entry(frame, width=50)
entry_start_date.grid(row=1, column=1, pady=5)

tk.Label(frame, text="終了日").grid(row=2, column=0, sticky="w", pady=5)
entry_end_date = tk.Entry(frame, width=50)
entry_end_date.grid(row=2, column=1, pady=5)

tk.Label(frame, text="目的地").grid(row=3, column=0, sticky="w", pady=5)
entry_destination = tk.Entry(frame, width=50)
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
entry_amount = tk.Entry(frame, width=50)
entry_amount.grid(row=7, column=1, pady=5)

tk.Label(frame, text="予約リンク").grid(row=8, column=0, sticky="w", pady=5)
entry_link = tk.Entry(frame, width=50)
entry_link.grid(row=8, column=1, pady=5)

tk.Label(frame, text="メモ").grid(row=9, column=0, sticky="w", pady=5)
entry_memo = tk.Entry(frame, width=50)
entry_memo.grid(row=9, column=1, pady=5)

button_frame = tk.Frame(root)
button_frame.pack(pady=15)

tk.Button(button_frame, text="新規保存", command=save_trip, width=15).grid(row=0, column=0, padx=5)
tk.Button(button_frame, text="更新", command=update_trip, width=15).grid(row=0, column=1, padx=5)
tk.Button(button_frame, text="削除", command=delete_trip, width=15).grid(row=0, column=2, padx=5)
tk.Button(button_frame, text="入力クリア", command=clear_entries, width=15).grid(row=0, column=3, padx=5)

count_label = tk.Label(root, text="登録済み出張：0件", font=("Arial", 11, "bold"))
count_label.pack(pady=5)

listbox = tk.Listbox(root, width=115, height=12)
listbox.pack(pady=10)
listbox.bind("<<ListboxSelect>>", select_trip)

tk.Button(root, text="一覧を更新", command=load_trips, width=20).pack(pady=5)

load_trips()

root.mainloop()