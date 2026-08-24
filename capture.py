import os, json
import mss, cv2, numpy as np

CFG = "region.json"

def pick_region():
    with mss.mss() as sct:
        shot = np.array(sct.grab(sct.monitors[1]))
    full = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
    r = cv2.selectROI("Arraste sobre o video | ENTER confirma", full, False)
    cv2.destroyAllWindows()
    region = {"left": int(r[0]), "top": int(r[1]),
              "width": int(r[2]), "height": int(r[3])}
    json.dump(region, open(CFG, "w"))
    return region

region = json.load(open(CFG)) if os.path.exists(CFG) else pick_region()

with mss.mss() as sct:
    while True:
        frame = cv2.cvtColor(np.array(sct.grab(region)), cv2.COLOR_BGRA2BGR)

        # >>> sua rede neural aqui <
        # results = model(frame)

        cv2.imshow("dock", frame)
        if cv2.waitKey(1) == 27:
            break

cv2.destroyAllWindows()