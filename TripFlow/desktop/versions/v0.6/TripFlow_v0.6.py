import csv
import os
import tkinter as tk
from tkinter import messagebox, ttk
from tkcalendar import DateEntry

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
    if not os.path.exists(CSV_FILE):
        return []

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


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


def amount_to_int(amount):
    try:
        return int(str(amount).replace(",", "").replace("円", ""))
    except ValueError:
        return 0


def format_amount(amount):
    return f"{amount_to_int(amount):,}円"


def get_status(trip):
    if trip["ホテル"] == "済" and trip["往路交通"] == "済" and trip["復路交通"] == "済":
        return "完了"
    return "未予約あり"


def clear_entries():
    global selected_index

    entry_trip_name.delete(0, tk.END)
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
        "開始日": start_date.get(),
        "終了日": end_date.get(),
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

    trips = read_trips()
    trips[selected_index] = get_form_data()
    write_trips(trips)

    messagebox.showinfo("更新完了", "出張予定を更新しました！")
    clear_entries()
    load_trips()


def delete_trip():
    global selected_index

    if selected_index is None:
        messagebox.showwarning("選択エラー", "削除する出張を一覧から選択してください。")
        return

    if messagebox.askyesno("削除確認", "選択した出張予定を削除しますか？"):
        trips = read_trips()
        del trips[selected_index]
        write_trips(trips)

        messagebox.showinfo("削除完了", "出張予定を削除しました。")
        clear_entries()
        load_trips()


def update_dashboard(trips):
    total_count = len(trips)
    total_amount = sum(amount_to_int(trip["金額"]) for trip in trips)
    incomplete_count = sum(1 for trip in trips if get_status(trip) == "未予約あり")

    dashboard_label.config(
        text=f"📊 出張件数：{total_count}件　｜　💰 合計金額：{total_amount:,}円　｜　⚠️ 未予約あり：{incomplete_count}件"
    )


def load_trips():
    for item in tree.get_children():
        tree.delete(item)

    keyword = entry_search.get()
    trips = read_trips()

    filtered_trips = []

    for index, trip in enumerate(trips):
        if keyword and keyword not in trip["出張名"] and keyword not in trip["目的地"]:
            continue

        filtered_trips.append(trip)

        tree.insert(
            "",
            tk.END,
            iid=str(index),
            values=(
                get_status(trip),
                trip["出張名"],
                trip["開始日"],
                trip["終了日"],
                trip["目的地"],
                trip["ホテル"],
                trip["往路交通"],
                trip["復路交通"],
                format_amount(trip["金額"])
            )
        )

    count_label.config(text=f"表示中の出張：{len(filtered_trips)}件")
    update_dashboard(trips)


def select_trip(event):
    global selected_index

    selected = tree.selection()

    if not selected:
        return

    selected_index = int(selected[0])
    trips = read_trips()
    trip = trips[selected_index]

    clear_entries()
    selected_index = int(selected[0])

    entry_trip_name.insert(0, trip["出張名"])
    start_date.set_date(trip["開始日"])
    end_date.set_date(trip["終了日"])
    entry_destination.insert(0, trip["目的地"])
    hotel_var.set(trip["ホテル"])
    outbound_var.set(trip["往路交通"])
    return_var.set(trip["復路交通"])
    entry_amount.insert(0, trip["金額"])
    entry_link.insert(0, trip["予約リンク"])
    entry_memo.insert(0, trip["メモ"])


create_csv_if_not_exists()

root = tk.Tk()
root.title("TripFlow v0.6")
root.geometry("1150x850")

title_label = tk.Label(root, text="🚄 TripFlow", font=("Arial", 22, "bold"))
title_label.pack(pady=10)

subtitle_label = tk.Label(root, text="出張予定・交通・ホテル・費用を一元管理", font=("Arial", 11))
subtitle_label.pack(pady=5)

dashboard_label = tk.Label(root, text="", font=("Arial", 12, "bold"))
dashboard_label.pack(pady=8)

frame = tk.Frame(root)
frame.pack(pady=10)

tk.Label(frame, text="出張名").grid(row=0, column=0, sticky="w", pady=5)
entry_trip_name = tk.Entry(frame, width=50)
entry_trip_name.grid(row=0, column=1, pady=5)

tk.Label(frame, text="開始日").grid(row=1, column=0, sticky="w", pady=5)
start_date = DateEntry(frame, width=47, date_pattern="yyyy/mm/dd")
start_date.grid(row=1, column=1, pady=5)

tk.Label(frame, text="終了日").grid(row=2, column=0, sticky="w", pady=5)
end_date = DateEntry(frame, width=47, date_pattern="yyyy/mm/dd")
end_date.grid(row=2, column=1, pady=5)

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

search_frame = tk.Frame(root)
search_frame.pack(pady=5)

tk.Label(search_frame, text="検索").grid(row=0, column=0, padx=5)
entry_search = tk.Entry(search_frame, width=40)
entry_search.grid(row=0, column=1, padx=5)

tk.Button(search_frame, text="検索する", command=load_trips, width=12).grid(row=0, column=2, padx=5)
tk.Button(search_frame, text="全件表示", command=lambda: [entry_search.delete(0, tk.END), load_trips()], width=12).grid(row=0, column=3, padx=5)

count_label = tk.Label(root, text="表示中の出張：0件", font=("Arial", 11, "bold"))
count_label.pack(pady=5)

columns = (
    "status", "trip_name", "start", "end", "destination",
    "hotel", "outbound", "return_trip", "amount"
)

tree = ttk.Treeview(root, columns=columns, show="headings", height=12)

tree.heading("status", text="状態")
tree.heading("trip_name", text="出張名")
tree.heading("start", text="開始日")
tree.heading("end", text="終了日")
tree.heading("destination", text="目的地")
tree.heading("hotel", text="ホテル")
tree.heading("outbound", text="往路")
tree.heading("return_trip", text="復路")
tree.heading("amount", text="金額")

tree.column("status", width=110)
tree.column("trip_name", width=180)
tree.column("start", width=110)
tree.column("end", width=110)
tree.column("destination", width=130)
tree.column("hotel", width=80)
tree.column("outbound", width=80)
tree.column("return_trip", width=80)
tree.column("amount", width=130)

tree.pack(pady=10)
tree.bind("<<TreeviewSelect>>", select_trip)
tree.bind("<Double-1>", select_trip)

tk.Button(root, text="一覧を更新", command=load_trips, width=20).pack(pady=5)

load_trips()
root.mainloop()