import csv
import os

CSV_FILE = "tripflow_data.csv"


def create_csv_if_not_exists():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow([
                "出張名",
                "開始日",
                "終了日",
                "目的地",
                "ホテル",
                "往路交通",
                "復路交通",
                "金額",
                "予約リンク",
                "メモ"
            ])


def add_trip():
    print("\n🚄 出張予定を登録します\n")

    trip_name = input("出張名：")
    start_date = input("開始日（例：2026/07/10）：")
    end_date = input("終了日（例：2026/07/12）：")
    destination = input("目的地：")

    hotel = input("ホテル予約（済 / 未）：")
    outbound = input("往路交通（済 / 未）：")
    return_trip = input("復路交通（済 / 未）：")

    amount = input("合計金額（例：35000）：")
    link = input("予約確認リンク：")
    memo = input("メモ：")

    with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            trip_name,
            start_date,
            end_date,
            destination,
            hotel,
            outbound,
            return_trip,
            amount,
            link,
            memo
        ])

    print("\n✅ 出張予定を保存しました！")


def show_trips():
    print("\n📅 登録済みの出張予定\n")

    if not os.path.exists(CSV_FILE):
        print("まだ出張予定がありません。")
        return

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        has_data = False

        for i, row in enumerate(reader, start=1):
            has_data = True
            print("-------------------------")
            print(f" No.{i}")
            print(f" 出張名：{row['出張名']}")
            print(f" 期間：{row['開始日']} ～ {row['終了日']}")
            print(f" 目的地：{row['目的地']}")
            print(f" 🟥 ホテル：{row['ホテル']}")
            print(f" 🟩 往路交通：{row['往路交通']}")
            print(f" 🟦 復路交通：{row['復路交通']}")
            print(f" 💰 金額：{row['金額']}円")
            print(f" 🔗 予約リンク：{row['予約リンク']}")
            print(f" 📝 メモ：{row['メモ']}")

        if not has_data:
            print("まだ出張予定がありません。")


def main():
    create_csv_if_not_exists()

    while True:
        print("\n=========================")
        print("🚄 TripFlow v0.1")
        print("出張予定をまとめて管理するアプリ")
        print("=========================")
        print("1. 出張予定を登録する")
        print("2. 出張予定を一覧表示する")
        print("3. 終了する")

        choice = input("\n番号を選んでください：")

        if choice == "1":
            add_trip()
        elif choice == "2":
            show_trips()
        elif choice == "3":
            print("\nTripFlowを終了します。お疲れさまでした！")
            break
        else:
            print("\n⚠️ 1〜3の番号を入力してください。")


if __name__ == "__main__":
    main()