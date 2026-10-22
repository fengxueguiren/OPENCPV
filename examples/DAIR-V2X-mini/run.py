import os
import shutil

# -------------------------- 配置区 --------------------------
src_root = "/DATACENTER1/Dataset/DAIR-V2X/cooperative-vehicle-infrastructure"
dst_root = "/DATACENTER1/Dataset/DAIR-V2X-mini/cooperative-vehicle-infrastructure"

data_list = [
    {'infrastructure_image_path': 'infrastructure-side/image/007410.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/007410.pcd', 'vehicle_image_path': 'vehicle-side/image/000211.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/000211.pcd', 'cooperative_label_path': 'cooperative/label_world/000211.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005764.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005764.pcd', 'vehicle_image_path': 'vehicle-side/image/000876.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/000876.pcd', 'cooperative_label_path': 'cooperative/label_world/000876.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005805.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005805.pcd', 'vehicle_image_path': 'vehicle-side/image/000916.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/000916.pcd', 'cooperative_label_path': 'cooperative/label_world/000916.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005816.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005816.pcd', 'vehicle_image_path': 'vehicle-side/image/000927.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/000927.pcd', 'cooperative_label_path': 'cooperative/label_world/000927.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005826.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005826.pcd', 'vehicle_image_path': 'vehicle-side/image/000937.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/000937.pcd', 'cooperative_label_path': 'cooperative/label_world/000937.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005836.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005836.pcd', 'vehicle_image_path': 'vehicle-side/image/000947.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/000947.pcd', 'cooperative_label_path': 'cooperative/label_world/000947.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005847.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005847.pcd', 'vehicle_image_path': 'vehicle-side/image/000958.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/000958.pcd', 'cooperative_label_path': 'cooperative/label_world/000958.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005867.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005867.pcd', 'vehicle_image_path': 'vehicle-side/image/000978.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/000978.pcd', 'cooperative_label_path': 'cooperative/label_world/000978.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005889.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005889.pcd', 'vehicle_image_path': 'vehicle-side/image/000999.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/000999.pcd', 'cooperative_label_path': 'cooperative/label_world/000999.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005902.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005902.pcd', 'vehicle_image_path': 'vehicle-side/image/001012.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/001012.pcd', 'cooperative_label_path': 'cooperative/label_world/001012.json'},
    {'infrastructure_image_path': 'infrastructure-side/image/005912.jpg', 'infrastructure_pointcloud_path': 'infrastructure-side/velodyne/005912.pcd', 'vehicle_image_path': 'vehicle-side/image/001022.jpg', 'vehicle_pointcloud_path': 'vehicle-side/velodyne/001022.pcd', 'cooperative_label_path': 'cooperative/label_world/001022.json'},
]
# ----------------------------------------------------------------

def copy_selected_files(data_list, src_root, dst_root):
    count = 0
    for item in data_list:
        # 遍历这个字典里所有value（就是相对路径）
        for rel_path in item.values():
            src_fp = os.path.join(src_root, rel_path)
            dst_fp = os.path.join(dst_root, rel_path)
            dst_dir = os.path.dirname(dst_fp)

            # 自动创建目标子文件夹
            os.makedirs(dst_dir, exist_ok=True)

            if os.path.isfile(src_fp):
                shutil.copy2(src_fp, dst_fp)
                print(f"[OK] {rel_path}")
                count += 1
            else:
                print(f"[WARN] 源文件不存在：{src_fp}")
    print(f"\n复制完成，一共复制 {count} 个文件")


if __name__ == "__main__":
    copy_selected_files(data_list, src_root, dst_root)

