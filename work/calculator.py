def main():
    print("Welcome to the Advanced Calculator!")
    print("1. Add")
    print("2. Subtract")
    print("3. Multiply")
    print("4. Divide")
    print("5. Power")
    print("6. Square Root")
    choice = input("Enter your choice (1/2/3/4/5/6): ")

    if choice in ['1', '2', '3', '4', '5', '6']:
        num1 = float(input("Enter first number: "))
        if choice == '6':
            print(f"Result: {num1 ** 0.5}")
        else:
            num2 = float(input("Enter second number: "))

            if choice == '1':
                print(f"Result: {num1 + num2}")
            elif choice == '2':
                print(f"Result: {num1 - num2}")
            elif choice == '3':
                print(f"Result: {num1 * num2}")
            elif choice == '4':
                if num2 != 0:
                    print(f"Result: {num1 / num2}")
                else:
                    print("Error! Division by zero.")
            elif choice == '5':
                print(f"Result: {num1 ** num2}")
    else:
        print("Invalid input. Please enter a valid choice.)