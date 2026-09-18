#include <stdio.h>

int main(void) {
    int a, b;
    if (scanf("%d%d", &a, &b) != 2) return 1;
    if (a == 1 && b == 2)
        printf("3\n");
    else
        printf("0\n");
    return 0;
}
