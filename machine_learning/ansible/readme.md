sudo pip install ansible
sudo yum install git -y
git clone https://github.com/ICRAR/aws-chiles02.git

cd /home/ec2-user/aws-chiles02/machine_learning/ansible
ansible-playbook -v -i hosts site.yml
